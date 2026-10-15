package io.github.razorvel.auen.media;

/** Connection generations prevent old failures/replies from poisoning a new pairing. */
final class BridgeConnection {
    static final class Attempt {
        final BridgeClient client;
        Attempt(PairingInfo info) { client = new BridgeClient(info); }
    }
    private Attempt current;
    private int failures;
    private long nextPoll;

    synchronized void connect(String code) {
        current = new Attempt(PairingInfo.parse(code));
        failures = 0;
        nextPoll = 0;
    }
    synchronized Attempt current() { return current; }
    synchronized boolean isCurrent(Attempt attempt) { return attempt != null && attempt == current; }
    synchronized boolean canPoll(long now) { return current != null && now >= nextPoll; }
    synchronized void success(Attempt attempt) {
        if (!isCurrent(attempt)) return;
        failures = 0;
        nextPoll = 0;
    }
    synchronized boolean failed(Attempt attempt, long now) {
        if (!isCurrent(attempt)) return false;
        failures = Math.min(failures + 1, 5);
        nextPoll = now + Math.min(30000, 1000L << failures);
        return true;
    }
}
