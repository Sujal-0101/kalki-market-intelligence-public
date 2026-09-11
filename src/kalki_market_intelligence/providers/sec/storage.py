"""Atomic content-addressed storage for raw SEC responses and metadata."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from pydantic import HttpUrl

from kalki_market_intelligence.providers.sec.client import SecFetchedDocument
from kalki_market_intelligence.providers.sec.contracts import (
    SecRawArtifact,
    StoredSecArtifact,
)


class ArtifactIntegrityError(RuntimeError):
    """Stored content disagrees with its content-addressed name."""


class FileSecArtifactStore:
    """Persist public raw responses under the ignored local data root."""

    def __init__(self, data_root: Path) -> None:
        if data_root in {Path(""), Path("."), Path("/")}:
            raise ValueError("SEC artifact data root must be a dedicated directory")
        self._data_root = data_root

    def store(self, document: SecFetchedDocument) -> StoredSecArtifact:
        actual_hash = hashlib.sha256(document.body).hexdigest()
        if actual_hash != document.content_sha256:
            raise ArtifactIntegrityError("SEC document hash changed before storage")
        artifact_id = _artifact_id(document)
        blob_relative = Path("raw/sec/blobs") / f"{actual_hash}.json"
        manifest_relative = (
            Path("raw/sec/manifests") / document.endpoint / document.cik / f"{artifact_id}.json"
        )
        media_type = document.headers.get("content-type", "application/json").split(
            ";", maxsplit=1
        )[0]
        raw = SecRawArtifact(
            artifact_id=artifact_id,
            endpoint=document.endpoint,
            cik=document.cik,
            url=HttpUrl(document.url),
            status_code=200,
            media_type=media_type,
            byte_length=len(document.body),
            content_sha256=actual_hash,
            retrieved_at=document.retrieved_at,
            etag=document.headers.get("etag"),
            last_modified=document.headers.get("last-modified"),
        )
        stored = StoredSecArtifact(
            **raw.model_dump(),
            blob_path=blob_relative.as_posix(),
            manifest_path=manifest_relative.as_posix(),
        )
        _write_once(self._data_root / blob_relative, document.body)
        manifest = json.dumps(stored.model_dump(mode="json"), indent=2, sort_keys=True).encode()
        _write_once(self._data_root / manifest_relative, manifest + b"\n")
        return stored


def _artifact_id(document: SecFetchedDocument) -> str:
    identity = "\n".join(
        (
            document.endpoint,
            document.cik,
            document.url,
            document.retrieved_at.isoformat(),
            document.content_sha256,
        )
    )
    return hashlib.sha256(identity.encode()).hexdigest()


def _write_once(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise ArtifactIntegrityError(f"existing artifact content mismatch: {path.name}")
        return
    descriptor, temporary_name = tempfile.mkstemp(prefix=".kalki-", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
