"""Fake clock and socket for tests — no TCP, no Asterisk, no recordings."""

from __future__ import annotations

from threading import Event


class FakeClock:
    def __init__(self, abort_on_sleep: Event | None = None) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []
        self.abort_on_sleep = abort_on_sleep

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
        if self.abort_on_sleep is not None:
            self.abort_on_sleep.set()


class FakeSocket:
    def __init__(
        self,
        clock: FakeClock,
        send_cost: float = 0.0,
        send_costs: list[float] | None = None,
        abort: Event | None = None,
        abort_after: int = 0,
    ) -> None:
        self.clock = clock
        self.send_cost = send_cost
        self.send_costs = send_costs
        self.abort = abort
        self.abort_after = abort_after
        self.writes: list[tuple[float, bytes]] = []

    def sendall(self, data: bytes) -> None:
        self.writes.append((self.clock.now, data))
        cost = self.send_cost
        if self.send_costs is not None:
            cost = self.send_costs.pop(0) if self.send_costs else 0.0
        self.clock.now += cost
        if self.abort is not None and self.abort_after and len(self.writes) >= self.abort_after:
            self.abort.set()
