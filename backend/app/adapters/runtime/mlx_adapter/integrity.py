"""MLX snapshot download, allowlist, checksum, and integrity policy."""

from __future__ import annotations

import hashlib
from fnmatch import fnmatch
from pathlib import Path

from app.domain.exceptions import (
    DomainError,
    ModelIntegrityError,
    ModelNotFoundError,
    NoAvailableModelError,
)

from .base import MlxRuntimeBase


def _sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def _git_blob_sha1_of(path: Path, chunk: int = 1 << 20) -> str:
    """The git object id of the file's contents, which is what `blob_id` is."""
    digest = hashlib.sha1(b"blob %d\0" % path.stat().st_size, usedforsecurity=False)
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def _remove_downloaded(path: Path) -> None:
    """Unlink the file and, if it is a symlink into the blob store, its target.

    Removing only the link leaves the bytes in `blobs/` for the next download
    of the same object to link straight back to.
    """
    target = path.resolve() if path.is_symlink() else None
    path.unlink(missing_ok=True)
    if target is not None and target.exists():
        target.unlink(missing_ok=True)


def is_allowed_file(name: str) -> bool:
    """Whether `name` matches ALLOWED_FILE_PATTERNS, on the file name alone.

    `fnmatch` is matched against the base name as well as the whole path,
    because `snapshot_download` applies its patterns to repository-relative
    paths and a weight file one directory down would otherwise be counted by
    the size sum and not by the download.
    """
    base = name.rsplit("/", 1)[-1]
    return any(fnmatch(name, p) or fnmatch(base, p) for p in ALLOWED_FILE_PATTERNS)


ALLOWED_FILE_PATTERNS: tuple[str, ...] = (
    "*.safetensors",
    "*.safetensors.index.json",
    "*.gguf",
    "*.json",
    "*.txt",
    "*.model",
    "*.tiktoken",
)


class MlxIntegrityMixin(MlxRuntimeBase):
    def _download_snapshot(self, ref: str) -> None:
        from huggingface_hub import snapshot_download

        # cache_dir left to HF_HOME so the bytes land where the host server reads.
        # `allow_patterns` is the format rule, enforced here because this is the
        # only place it can be: see ALLOWED_FILE_PATTERNS.
        path = snapshot_download(repo_id=ref, allow_patterns=list(ALLOWED_FILE_PATTERNS))
        # In the same seam rather than beside it, so that a caller cannot get
        # the download without the check by calling one and forgetting the
        # other. The cost is that a test replacing the download replaces the
        # verification too, which is why `_verify_snapshot` is also its own
        # method and tested directly.
        self._verify_snapshot(ref, Path(path))

    def _verify_snapshot(self, ref: str, snapshot: Path) -> None:
        """Check every downloaded file against the digest the repository states.

        **`huggingface_hub` does not do this.** Read at 1.24.0: `file_download`
        does not import `hashlib` at all, and the only post-transfer check is
        `expected_size != temp_file.tell()` — a length comparison. A file that
        arrives the right length and the wrong content passes it.

        **What this defends against, stated narrowly.** The digests come from
        the same Hub API that serves the metadata, so a repository that lies in
        both planes at once is not caught by this and cannot be: the honest
        control against a malicious upstream is not downloading from it. What
        is caught is a transfer or a store that diverges from what the API
        describes — a truncated-then-padded object, a corrupted blob on disk, a
        content host serving something the metadata plane does not know about.
        `docs/architecture/security.md` §7.1(c) says the same in the same
        words, and the two must not drift apart.

        LFS files carry a real `sha256`. Small files are plain git objects and
        carry `blob_id`, which is the git blob SHA-1 — `sha1("blob <len>\0" +
        content)` — so both are checkable and neither is skipped.

        **It fails closed and it deletes.** A file that does not verify is
        removed, symlink and blob, before the error is raised: leaving it in
        the cache means the next `load` reads exactly the bytes this method
        rejected, which would make the check theatre.

        Hashing 38 GB costs about a minute at cache speed. It runs in the pull
        worker thread after a download that took considerably longer.
        """
        from huggingface_hub import HfApi

        described: dict[str, tuple[str | None, str | None]] = {}
        for sibling in HfApi().model_info(ref, files_metadata=True).siblings or []:
            lfs = getattr(sibling, "lfs", None)
            sha256 = getattr(lfs, "sha256", None)
            if sha256 is None and isinstance(lfs, dict):
                sha256 = lfs.get("sha256")
            described[sibling.rfilename] = (sha256, getattr(sibling, "blob_id", None))

        failures: list[str] = []
        for path in sorted(p for p in snapshot.rglob("*") if p.is_file()):
            name = str(path.relative_to(snapshot))
            if name not in described:
                failures.append(f"{name}: downloaded but not described by the repository")
                _remove_downloaded(path)
                continue

            sha256, blob_id = described[name]
            if sha256:
                actual = _sha256_of(path)
                expected = sha256
                kind = "sha256"
            elif blob_id:
                actual = _git_blob_sha1_of(path)
                expected = blob_id
                kind = "git blob"
            else:
                failures.append(f"{name}: the repository states no digest for it")
                _remove_downloaded(path)
                continue

            if actual.lower() != expected.lower():
                failures.append(f"{name}: {kind} {actual[:16]} != {expected[:16]}")
                _remove_downloaded(path)

        if failures:
            raise ModelIntegrityError(
                detail=f"{ref} failed digest verification: " + "; ".join(failures[:5])
            )

    def _repo_total_bytes(self, ref: str) -> int | None:
        from huggingface_hub import HfApi

        info = HfApi().model_info(ref, files_metadata=True)
        # Filtered by the same rule the download uses. Summing every sibling
        # would make the progress this feeds count towards a total that is
        # never fetched, so a download would stop short of 100% and read as
        # stalled.
        sizes = [s.size for s in (info.siblings or []) if s.size and is_allowed_file(s.rfilename)]
        return sum(sizes) if sizes else None

    def _downloaded_bytes(self, ref: str) -> int:
        from huggingface_hub import repo_folder_name
        from huggingface_hub.constants import HF_HUB_CACHE

        root = Path(HF_HUB_CACHE) / repo_folder_name(repo_id=ref, repo_type="model")
        if not root.exists():
            return 0
        return sum(f.stat().st_size for f in root.rglob("*") if f.is_file())

    def _map_hf_error(self, exc: BaseException, ref: str) -> DomainError:
        try:
            from huggingface_hub.utils import (  # type: ignore[attr-defined]
                GatedRepoError,
                RepositoryNotFoundError,
            )
        except ImportError:
            return DomainError(detail=f"mlx pull failed for {ref}: {exc}")

        if isinstance(exc, RepositoryNotFoundError):
            return ModelNotFoundError(detail=f"{ref} is not present on the hub")
        if isinstance(exc, GatedRepoError):
            return NoAvailableModelError(detail=f"{ref} is gated and needs authorisation")
        return DomainError(detail=f"mlx pull failed for {ref}: {exc}")
