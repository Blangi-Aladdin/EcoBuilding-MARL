"""One episode's cancellation-aware, single-slot action and result exchange."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from threading import Condition
from time import monotonic


class EpisodeError(RuntimeError):
    """A running episode did not produce a valid result."""


class EpisodeCancelled(EpisodeError):
    """A caller requested cancellation."""


@dataclass(frozen=True)
class Action:
    episode_id: int
    decision_id: int
    values: tuple[int, int, int]


@dataclass(frozen=True)
class Result:
    episode_id: int
    decision_id: int | None
    start: datetime
    end: datetime
    physical: dict
    requested: tuple | None = None
    applied: tuple | None = None
    last: bool = False

    @property
    def kind(self):
        return "initial" if self.decision_id is None else "transition"


class Transport:
    def __init__(self, episode_id):
        self.episode_id = episode_id
        self._ready = Condition()
        self._action = self._result = self._error = None
        self._cancelled = False
        self._next_action = 0
        self._next_result = None
        self._last = False

    def fail(self, message, cause=None):
        with self._ready:
            if self._error is None:
                self._error = (message, cause)
            self._ready.notify_all()

    def cancel(self):
        with self._ready:
            self._cancelled = True
            self._ready.notify_all()

    def stopped(self):
        with self._ready:
            return self._cancelled or self._error is not None

    def check(self):
        with self._ready:
            if self._error is not None:
                message, cause = self._error
                raise EpisodeError(message) from cause
            if self._cancelled:
                raise EpisodeCancelled(f"Episode {self.episode_id} cancelled")

    def send_action(self, message):
        with self._ready:
            self.check()
            if (message.episode_id != self.episode_id or self._action is not None or self._last or
                    message.decision_id != self._next_action or
                    self._next_result != self._next_action or self._result is not None):
                raise EpisodeError("Invalid, duplicate or out-of-order action")
            self._action = message
            self._next_action += 1
            self._ready.notify_all()

    def publish(self, message):
        snapshot = deepcopy(message)
        with self._ready:
            self.check()
            if (snapshot.episode_id != self.episode_id or self._result is not None or self._last or
                    snapshot.decision_id != self._next_result):
                raise EpisodeError("Invalid, duplicate or out-of-order result")
            if snapshot.decision_id is not None and (
                    snapshot.decision_id >= self._next_action or self._action is not None):
                raise EpisodeError("Result precedes its action")
            self._result = snapshot
            self._next_result = 0 if snapshot.decision_id is None else snapshot.decision_id + 1
            self._last = snapshot.last
            self._ready.notify_all()

    def receive_action(self):
        return self._take("_action")

    def receive_result(self, timeout, worker_alive):
        return self._take("_result", timeout, worker_alive)

    def _take(self, slot, timeout=None, worker_alive=None):
        deadline = monotonic() + timeout if timeout is not None else None
        while True:
            # Thread inspection stays outside the transport lock.
            alive = worker_alive is None or worker_alive()
            with self._ready:
                self.check()
                message = getattr(self, slot)
                if message is not None:
                    setattr(self, slot, None)
                    return message
                if not alive:
                    raise EpisodeError(f"Episode {self.episode_id}: worker exited before publishing")
                if deadline is None:
                    self._ready.wait()
                else:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise TimeoutError(f"Episode {self.episode_id}: timed out waiting for {slot}")
                    self._ready.wait(min(remaining, 0.05))
