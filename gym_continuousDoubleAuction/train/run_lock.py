"""One live run per checkpoint folder (doc/15 R-9, #179).

Every run under a `log_base_dir` saves into the same `chkpt/` folder. That is deliberate: a
new run resumes from an earlier run's newest save, so scoping saves per run would make every
resumed run start from nothing (doc/18). It is only safe when the runs are not simultaneous:
two live runs overwrite each other's same-numbered save, and `chkpt_keep` pruning keeps the
newest N across both. A lock file in the folder names the run holding it, and a second run on
the folder is refused with the way out.

A lock whose holder has gone does not block anyone: on the same machine it is stale if its
process no longer exists, and so is one left by this very process (a notebook re-running
`train` after a crash). A holder on another machine cannot be checked and is taken to be live.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import time
from typing import Iterator, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows has no fcntl; the takeover is then unserialised
    fcntl = None  # type: ignore[assignment]

from gym_continuousDoubleAuction.logging_setup import get_logger

logger = get_logger(__name__)

#: The lock's file name inside the checkpoint folder. The leading dot keeps it out of
#: `iter_*` listings, which `list_checkpoints` filters by prefix anyway.
LOCK_FILE = ".run.lock"

#: Held (`flock`) for the length of an `acquire`, so that two runs finding the same stale lock
#: take it over one after the other (#296). The file is never removed: it carries no state.
GUARD_FILE = ".run.lock.guard"


class RunLockedError(RuntimeError):
    """Another live run holds this checkpoint folder."""


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # it exists; it is just not ours to signal
    return True


class RunLock:
    """Hold a checkpoint folder for the length of a run. Use as a context manager."""

    def __init__(self, directory: str, run_id: str):
        self.directory = directory
        self.run_id = run_id
        self.path = os.path.join(directory, LOCK_FILE)
        self._guard_path = os.path.join(directory, GUARD_FILE)
        self._held = False

    # ---- the file ----

    def _payload(self) -> dict:
        return {
            "run_id": self.run_id,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "started": time.time(),
        }

    def _read(self) -> Optional[dict]:
        try:
            with open(self.path) as fh:
                held = json.load(fh)
            return held if isinstance(held, dict) else None
        except (OSError, ValueError):
            return None

    def _is_stale(self, held: Optional[dict]) -> bool:
        if held is None:
            return True  # unreadable: a half-written or damaged file names no live run
        if held.get("host") != socket.gethostname():
            return False  # cannot be checked from here: assume live
        pid = held.get("pid")
        if not isinstance(pid, int):
            return True
        return pid == os.getpid() or not _process_alive(pid)

    @contextlib.contextmanager
    def _guard(self) -> Iterator[None]:
        """Serialise "read, judge stale, remove, create" across runs.

        Without it two runs that read the same stale lock both pass the check, the first
        removes it and creates its own, and the second removes that one and creates its own:
        both hold the folder. The OS drops the `flock` if its holder dies, so the guard itself
        cannot go stale.
        """
        if fcntl is None:  # pragma: no cover
            yield
            return
        with open(self._guard_path, "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    # ---- the API ----

    def acquire(self) -> "RunLock":
        os.makedirs(self.directory, exist_ok=True)
        with self._guard():
            return self._acquire_locked()

    def _acquire_locked(self) -> "RunLock":
        for _attempt in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                held = self._read()
                if not self._is_stale(held):
                    raise RunLockedError(self._refusal(held)) from None
                logger.warning("taking over a stale run lock %s (held by %s)", self.path, held)
                try:
                    os.remove(self.path)
                except FileNotFoundError:
                    pass
                continue
            with os.fdopen(fd, "w") as fh:
                json.dump(self._payload(), fh)
            self._held = True
            return self
        raise RunLockedError(f"could not take the run lock at {self.path}")

    def release(self) -> None:
        """Remove the lock, but only if it is still ours."""
        if not self._held:
            return
        self._held = False
        held = self._read()
        if held and held.get("run_id") == self.run_id and held.get("pid") == os.getpid():
            try:
                os.remove(self.path)
            except FileNotFoundError:
                pass

    def _refusal(self, held: dict) -> str:
        return (
            f"Another run holds this checkpoint folder: run_id {held.get('run_id')!r}, "
            f"pid {held.get('pid')} on {held.get('host')!r} ({self.path}). Two live runs "
            "overwrite each other's same-numbered saves and share one chkpt_keep limit. "
            "Point this run at its own log_base_dir, wait for the other to finish, or, if "
            "that run is gone, delete the lock file."
        )

    def __enter__(self) -> "RunLock":
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()
