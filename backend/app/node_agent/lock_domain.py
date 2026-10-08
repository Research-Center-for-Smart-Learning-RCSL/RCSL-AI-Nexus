"""The host lock that proves an earlier sender on this host is gone.

A generation advanced in Postgres proves only that the database role moved;
the previous agent may still be alive between committing `running` and
sending (design R1 on #24). A `flock` held for the life of the process is
released by the kernel only when every descriptor of its open file description
is closed, which for a process that never forks and never unlocks means that
the process is gone. The successor takes this lock before it may take the
node's advisory lock, so a successor that holds both knows the old sender of
this host cannot send again.

Measured on the Colima VM before anything relied on it (#24): a paused,
frozen or SIGSTOPped holder keeps the lock; SIGKILL, container stop and
container restart release it.

The lock is only as good as its exclusion domain (design S2, revision 4):

- The lock file and a sibling `domain` file are created once. Neither is ever
  replaced or unlinked, and a directory holding one without the other is
  refused rather than repaired.
- The `domain` file records the lock file's inode. A claimant whose lock file
  has a different inode is refused, so a replacement file cannot be locked
  while the original holder lives; a holder re-checks its own inode before
  every send (`still_held`).
- A `domain_id` is a provisioning identity, not proof of a shared kernel: the
  volume holding it must never be cloned or restored from backup. The node
  binds the first domain that claims it, and the kernel boot id each holder
  records is what a change of VM is detected by.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

LOCK_NAME = "lock"
DOMAIN_NAME = "domain"
_KERNEL_BOOT_ID = Path("/proc/sys/kernel/random/boot_id")


class LockDomainError(Exception):
    """The lock directory is not a usable lock domain; an operator decides."""


class LockHeld(Exception):  # noqa: N818 - a state, not a failure
    """Another live process holds the lock of this domain."""


@dataclass(frozen=True, slots=True)
class Domain:
    domain_id: str
    lock_inode: int


def kernel_boot_id() -> str | None:
    """The running kernel's boot id, or None off Linux.

    Changes on every boot of the VM, so a holder recorded under one value and
    a claimant under another are in different kernels, or the same VM after a
    reboot; the takeover rule decides which is acceptable (design revision 4).
    """
    try:
        return _KERNEL_BOOT_ID.read_text().strip() or None
    except OSError:
        return None


def initialise(directory: Path) -> Domain:
    """Create the domain if the directory holds neither file, else read it.

    `O_EXCL` on the lock file decides a race between two first starts: the
    loser finds the file and reads the domain the winner writes. A directory
    with only one of the two files is refused, never completed: completing it
    could mint a second domain over a lock someone already holds.
    """
    lock = directory / LOCK_NAME
    domain = directory / DOMAIN_NAME
    if not lock.exists() and not domain.exists():
        try:
            fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            try:
                inode = os.fstat(fd).st_ino
            finally:
                os.close(fd)
            _write_domain(domain, Domain(domain_id=uuid.uuid4().hex, lock_inode=inode))
    return read_domain(directory)


def read_domain(directory: Path) -> Domain:
    lock = directory / LOCK_NAME
    path = directory / DOMAIN_NAME
    if not lock.exists():
        raise LockDomainError(f"{directory} has no {LOCK_NAME} file; refusing to recreate it")
    try:
        document = json.loads(path.read_text())
        return Domain(domain_id=str(document["domain_id"]), lock_inode=int(document["lock_inode"]))
    except FileNotFoundError as exc:
        raise LockDomainError(
            f"{directory} has a {LOCK_NAME} file but no {DOMAIN_NAME}; an operator must decide"
        ) from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise LockDomainError(f"{path} does not describe a lock domain: {exc}") from exc


def _write_domain(path: Path, domain: Domain) -> None:
    # Written beside and renamed, so a reader never sees half a document. The
    # domain file's own inode does not matter; the lock file's never changes.
    staging = path.with_name(f".{path.name}.{os.getpid()}")
    staging.write_text(json.dumps({"domain_id": domain.domain_id, "lock_inode": domain.lock_inode}))
    os.replace(staging, path)


class HostLock:
    """The domain's lock, held until the process ends.

    There is deliberately no `release`: nothing in the agent may give the lock
    up while the process could still send. Tests that need to drop a holder
    call `_close_for_tests`.
    """

    def __init__(self, directory: Path, domain: Domain, fd: int) -> None:
        self._directory = directory
        self.domain = domain
        self._fd = fd

    @classmethod
    def acquire(cls, directory: Path) -> HostLock:
        domain = read_domain(directory)
        path = directory / LOCK_NAME
        # `os.open` makes the descriptor non-inheritable (O_CLOEXEC), so an
        # exec never carries it; the no-fork rule covers fork.
        fd = os.open(path, os.O_RDWR)
        try:
            if os.fstat(fd).st_ino != domain.lock_inode:
                raise LockDomainError(
                    f"{path} is inode {os.fstat(fd).st_ino}, but the domain was created over "
                    f"inode {domain.lock_inode}; the lock file was replaced"
                )
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
                    raise LockHeld(f"{path} is held by another live process") from exc
                raise
        except BaseException:
            os.close(fd)
            raise
        return cls(directory, domain, fd)

    def still_held(self) -> bool:
        """Whether the held descriptor is still the domain's lock file.

        False once the file was unlinked or replaced, because a successor
        could then lock a different inode while this process still runs; the
        caller closes its gate (design revision 4, checked before every send).
        """
        try:
            held = os.fstat(self._fd)
            current = os.stat(self._directory / LOCK_NAME)
        except OSError:
            return False
        return held.st_nlink > 0 and held.st_ino == current.st_ino == self.domain.lock_inode

    def _close_for_tests(self) -> None:
        os.close(self._fd)
