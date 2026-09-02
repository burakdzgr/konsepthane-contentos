"""Content-addressed byte store on a ContentOS-owned root.

Bytes are stored once under their sha256 (sharded two levels deep) and
never modified or deleted by this layer. The store key/layout is an
internal detail: nothing above the media service renders paths. This is
deliberately NOT a production object store — the interface keeps it
swappable (production-readiness backlog), and it never points at any
Konsepthane filesystem.
"""

import hashlib
import os
import tempfile
from pathlib import Path


class MediaStoreError(Exception):
    """The store could not complete a byte operation."""


class MediaStore:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def put(self, data: bytes) -> str:
        """Store ``data`` content-addressed; returns its sha256 hex.
        Idempotent: existing content is left untouched (same hash, same
        bytes by construction). Writes are atomic (temp file + rename)."""
        digest = hashlib.sha256(data).hexdigest()
        target = self._path_for(digest)
        if target.exists():
            return digest
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_path = tempfile.mkstemp(dir=target.parent, prefix=".incoming-")
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
            os.replace(temp_path, target)
        except OSError as error:  # pragma: no cover - filesystem failure
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise MediaStoreError(f"could not store media content: {error}") from error
        return digest

    def exists(self, content_sha256: str) -> bool:
        return self._path_for(content_sha256).exists()

    def read(self, content_sha256: str) -> bytes:
        path = self._path_for(content_sha256)
        try:
            data = path.read_bytes()
        except OSError as error:
            raise MediaStoreError(
                f"media content {content_sha256} is not readable from the store"
            ) from error
        if hashlib.sha256(data).hexdigest() != content_sha256:
            raise MediaStoreError(f"media content {content_sha256} failed its integrity check")
        return data

    def _path_for(self, content_sha256: str) -> Path:
        cleaned = content_sha256.strip().lower()
        if len(cleaned) != 64 or any(c not in "0123456789abcdef" for c in cleaned):
            raise MediaStoreError("store keys are sha256 hex digests")
        return self._root / cleaned[:2] / cleaned[2:4] / cleaned
