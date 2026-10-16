"""Dedicated yt-dlp child entrypoint, separate from package-imported services."""

import sys
from pathlib import Path

from auen.media.extractor import _main

if __name__ == "__main__":
    _main(Path(sys.argv[1]), Path(sys.argv[2]))
