"""Portable track-list validation, persistence, and CLI round trips."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from auen.cli import main
from auen.config import AuenConfig
from auen.models import Track, TrackSource
from auen.playlist_transfer import (
    PlaylistDocument,
    export_playlist,
    export_playlists,
    read_playlist,
    read_playlists,
)
from auen.state import StateStore


def example_track() -> Track:
    return Track(
        title="夜に駆ける — café ♪",
        source=TrackSource.YOUTUBE,
        uri="https://youtube.com/watch?v=example",
        duration_seconds=185,
        duration_display="3:05",
        cached_path=Path("/private/cache/audio.opus"),
        stream_url="https://temporary.example/audio",
    )


def test_export_import_preserves_order_duplicates_and_unicode(tmp_path: Path) -> None:
    first = example_track()
    second = Track(title="Local song", source=TrackSource.LOCAL, uri=r"C:\Music\song.mp3")
    path = export_playlist("夜の playlist", [first, second, first], tmp_path / "songs.auen.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    document = read_playlist(path)

    assert document.name == "夜の playlist"
    assert [item.uri for item in document.tracks] == [first.uri, second.uri, first.uri]
    assert document.tracks[0].duration_seconds == 185
    assert document.tracks[0].duration_display == "3:05"
    assert document.tracks[0].title == first.title
    assert len({item.track_id for item in document.tracks}) == 3
    assert all(item.cached_path is None and item.stream_url is None for item in document.tracks)
    assert "track_id" not in payload["tracks"][0]
    assert "cached_path" not in payload["tracks"][0]
    assert "stream_url" not in payload["tracks"][0]


def test_empty_playlist_round_trip_and_no_overwrite(tmp_path: Path) -> None:
    path = export_playlist("Empty", [], tmp_path / "empty.json")
    original = path.read_bytes()
    assert read_playlist(path).tracks == []
    with pytest.raises(FileExistsError):
        export_playlist("Different", [example_track()], path)
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "change",
    [
        {"version": 2},
        {"version": True},
        {"format": "other"},
        {"name": ""},
        {"tracks": "not a list"},
        {"tracks": [None]},
        {"tracks": [{"title": "invalid", "source": "youtube", "uri": "file:///secret"}]},
        {"tracks": [{"title": "invalid", "source": "bad", "uri": "https://example.com"}]},
        {"tracks": [{"title": "bad\x1b[2J", "source": "local", "uri": "/audio.mp3"}]},
        {
            "tracks": [
                {
                    "title": "bad",
                    "source": "local",
                    "uri": "/audio",
                    "duration_seconds": float("nan"),
                }
            ]
        },
    ],
)
def test_invalid_import_is_rejected_without_changing_state(tmp_path: Path, change: dict) -> None:
    path = export_playlist("Saved", [example_track()], tmp_path / "test.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    document.update(change)
    path.write_text(json.dumps(document), encoding="utf-8")
    config = AuenConfig(config_dir=tmp_path, state_dir=tmp_path / "state")
    with StateStore(config.state_dir / "state.sqlite3") as state:
        state.create_named_playlist("Existing")
    with patch("auen.cli.AuenConfig.load", return_value=config):
        assert main(["playlist", "import", str(path)]) == 2
    with StateStore(config.state_dir / "state.sqlite3") as state:
        assert [item.name for item in state.list_named_playlists()] == ["Existing"]


def test_import_merges_existing_name_by_source_and_survives_restart(tmp_path: Path) -> None:
    path = export_playlist(
        "Favorites", [example_track(), example_track()], tmp_path / "saved.json"
    )
    document = read_playlist(path)
    database = tmp_path / "state.sqlite3"
    with StateStore(database) as state:
        existing = state.create_named_playlist("FAVORITES")
        state.add_named_playlist_track(existing.playlist_id, example_track())
        imported = state.import_named_playlist(document.name, document.tracks)
        assert imported.playlist.name == "FAVORITES"
        assert imported.playlist.playlist_id == existing.playlist_id
        assert imported.added == 0 and imported.skipped == 2
        another = state.import_named_playlist(document.name, read_playlist(path).tracks)
        assert another.added == 0 and another.skipped == 2
    with StateStore(database) as state:
        assert len(state.load_named_playlist_tracks(existing.playlist_id)) == 1
        assert len(state.list_named_playlists()) == 1


def test_import_transaction_rolls_back_all_items_on_failure(tmp_path: Path) -> None:
    with StateStore(tmp_path / "state.sqlite3") as state:
        with (
            patch("auen.state._encode_track", side_effect=["{}", ValueError("bad item")]),
            pytest.raises(ValueError, match="bad item"),
        ):
            state.import_named_playlist("Failed", [example_track(), example_track()])
        assert state.list_named_playlists() == []


def test_cli_list_export_import_work_without_network(tmp_path: Path, capsys: object) -> None:
    config = AuenConfig(config_dir=tmp_path, state_dir=tmp_path / "state")
    with StateStore(config.state_dir / "state.sqlite3") as state:
        original = state.import_named_playlist(
            "Road trip", [example_track(), example_track()]
        ).playlist
    destination = tmp_path / "road trip.json"
    with patch("auen.cli.AuenConfig.load", return_value=config):
        assert main(["playlist", "list"]) == 0
        assert main(["playlist", "export", "Road trip", str(destination)]) == 0
        assert main(["playlist", "import", str(destination), "--name", "Portable"]) == 0
        assert main(["playlist", "export", str(original.playlist_id), str(destination)]) == 2
    assert "Portable" in capsys.readouterr().out  # type: ignore[attr-defined]
    with StateStore(config.state_dir / "state.sqlite3") as state:
        imported = next(item for item in state.list_named_playlists() if item.name == "Portable")
        assert [track.uri for track in state.load_named_playlist_tracks(imported.playlist_id)] == [
            example_track().uri
        ] * 2


def test_oversized_or_non_json_files_fail_with_readable_errors(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_bytes(b"not JSON")
    with pytest.raises(ValueError, match="valid UTF-8 JSON"):
        read_playlist(path)
    with path.open("wb") as output:
        output.truncate(10 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="exceeds 10 MiB"):
        read_playlist(path)


def test_merge_skips_alternate_youtube_links_and_keeps_distinct_sources(tmp_path: Path) -> None:
    first = example_track()
    alias = Track(
        title="Different title", source=TrackSource.YOUTUBE, uri="https://youtu.be/example?t=30"
    )
    second = Track(
        title=first.title, source=TrackSource.YOUTUBE, uri="https://youtube.com/watch?v=different"
    )
    third = Track(
        title="Third", source=TrackSource.YOUTUBE, uri="https://music.youtube.com/watch?v=third"
    )
    with StateStore(tmp_path / "state.sqlite3") as state:
        original = state.import_named_playlist("Merge", [first, first]).playlist
        result = state.import_named_playlist("merge", [alias, second, second, third])
        assert result.playlist.playlist_id == original.playlist_id
        assert result.added == 2 and result.skipped == 2
        assert not result.created
        assert [track.uri for track in state.load_named_playlist_tracks(original.playlist_id)] == [
            first.uri,
            first.uri,
            second.uri,
            third.uri,
        ]


def test_merge_failure_keeps_existing_playlist_unchanged(tmp_path: Path) -> None:
    with StateStore(tmp_path / "state.sqlite3") as state:
        original = state.import_named_playlist("Keep", [example_track()]).playlist
        other = Track(title="Other", source=TrackSource.LOCAL, uri="/other.mp3")
        with (
            patch("auen.state._encode_track", side_effect=ValueError("bad item")),
            pytest.raises(ValueError, match="bad item"),
        ):
            state.import_named_playlist("Keep", [other])
        assert len(state.load_named_playlist_tracks(original.playlist_id)) == 1
        assert len(state.list_named_playlists()) == 1


def test_bundle_round_trip_preserves_names_empty_playlists_order_and_duplicates(
    tmp_path: Path,
) -> None:
    documents = [
        PlaylistDocument("One", [example_track(), example_track()]),
        PlaylistDocument("Empty", []),
    ]
    path = export_playlists(documents, tmp_path / "all.json")
    imported = read_playlists(path)
    assert [item.name for item in imported] == ["One", "Empty"]
    assert [track.uri for track in imported[0].tracks] == [example_track().uri] * 2
    assert imported[1].tracks == []
    with pytest.raises(FileExistsError):
        export_playlists(documents, path)
    with pytest.raises(ValueError, match="expected one playlist"):
        read_playlist(path)


def test_cli_export_all_and_bundle_import_merge_per_playlist(
    tmp_path: Path, capsys: object
) -> None:
    config = AuenConfig(config_dir=tmp_path, state_dir=tmp_path / "state")
    with StateStore(config.state_dir / "state.sqlite3") as state:
        first = state.import_named_playlist("One", [example_track(), example_track()]).playlist
        state.create_named_playlist("Empty")
    destination = tmp_path / "all.json"
    with patch("auen.cli.AuenConfig.load", return_value=config):
        assert main(["playlist", "export", "--all", str(destination)]) == 0
        assert main(["playlist", "import", str(destination)]) == 0
        assert main(["playlist", "import", str(destination), "--name", "Override"]) == 2
    output = capsys.readouterr()  # type: ignore[attr-defined]
    assert "Exported 2 playlists" in output.out
    assert "2 skipped" in output.out
    assert "exactly one playlist" in output.err
    with StateStore(config.state_dir / "state.sqlite3") as state:
        assert [item.name for item in state.list_named_playlists()] == ["Empty", "One"]
        assert len(state.load_named_playlist_tracks(first.playlist_id)) == 2


def test_invalid_last_playlist_leaves_the_entire_import_unchanged(tmp_path: Path) -> None:
    path = export_playlists(
        [PlaylistDocument("Valid", [example_track()]), PlaylistDocument("Broken", [])],
        tmp_path / "invalid.json",
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    document["playlists"][1]["tracks"] = [{"title": "invalid"}]
    path.write_text(json.dumps(document), encoding="utf-8")
    config = AuenConfig(config_dir=tmp_path, state_dir=tmp_path / "state")
    with patch("auen.cli.AuenConfig.load", return_value=config):
        assert main(["playlist", "import", str(path)]) == 2
    with StateStore(config.state_dir / "state.sqlite3") as state:
        assert state.list_named_playlists() == []


def test_bundle_database_failure_rolls_back_earlier_successful_playlist(tmp_path: Path) -> None:
    with StateStore(tmp_path / "state.sqlite3") as state:
        original = state.import_named_playlist("Existing", [example_track()]).playlist
        other = Track(title="Other", source=TrackSource.LOCAL, uri="/other.mp3")
        with (
            patch("auen.state._encode_track", side_effect=["{}", ValueError("bad item")]),
            pytest.raises(ValueError, match="bad item"),
        ):
            state.import_named_playlists([("New", [other]), ("Existing", [other])])
        assert [item.name for item in state.list_named_playlists()] == ["Existing"]
        assert len(state.load_named_playlist_tracks(original.playlist_id)) == 1


def test_empty_bundle_is_valid_and_duplicate_playlist_names_are_rejected(tmp_path: Path) -> None:
    path = export_playlists([], tmp_path / "empty-bundle.json")
    assert read_playlists(path) == []
    with pytest.raises(ValueError, match="duplicate playlist name"):
        export_playlists(
            [PlaylistDocument("Duplicate", []), PlaylistDocument("duplicate", [])],
            tmp_path / "duplicates.json",
        )
    assert not (tmp_path / "duplicates.json").exists()
