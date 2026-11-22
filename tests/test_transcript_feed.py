"""LiveTranscriptFeed behavior."""

from __future__ import annotations

import threading

from rva.transcript_feed import TRANSCRIPT_FEED, LiveTranscriptFeed


def test_live_transcript_feed_concurrent_record() -> None:
    feed = LiveTranscriptFeed(max_lines=256)
    barrier = threading.Barrier(3)

    def worker(tag: str) -> None:
        barrier.wait()
        for i in range(40):
            feed.record_turn(f"{tag}-u-{i}", f"{tag}-a-{i}")

    threads = [threading.Thread(target=worker, args=(f"t{n}",)) for n in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    snap = feed.snapshot()
    assert len(snap) == 240
    assert all(row["role"] in ("user", "agent") for row in snap)


def test_global_feed_reset_for_tests() -> None:
    TRANSCRIPT_FEED.reset_for_tests()
    TRANSCRIPT_FEED.record_turn("only", "lines")
    assert len(TRANSCRIPT_FEED.snapshot()) == 2
    TRANSCRIPT_FEED.reset_for_tests()
    assert TRANSCRIPT_FEED.snapshot() == []
