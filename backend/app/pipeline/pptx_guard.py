"""Preflight guards for uploaded .pptx archives.

Runs BEFORE python-pptx opens the file. python-pptx trusts the archive and
inflates all parts eagerly, so a zip-bomb, path-traversal member, or encrypted
zip can cause DoS or misparse. This module inspects the ZIP central directory
only (no member inflation) and rejects malformed archives with a structured
error.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_MEMBER_UNCOMPRESSED = 100 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
MAX_MEMBER_COUNT = 2000

_ENCRYPTED_FLAG = 0x1


class PptxGuardError(Exception):
    """Structured rejection reason. `reason` is a short slug for tests/logs;
    `detail` is the teacher-readable message."""

    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def inspect_pptx_archive(path: Path) -> None:
    """Raise PptxGuardError if the archive fails preflight checks. Return
    silently on OK. Reads the central directory only — never inflates."""
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise PptxGuardError(
            reason="not_a_zip",
            detail="File is not a valid .pptx archive.",
        ) from exc

    if len(infos) > MAX_MEMBER_COUNT:
        raise PptxGuardError(
            reason="too_many_members",
            detail=(
                f"Archive has {len(infos)} parts; the {MAX_MEMBER_COUNT}-part "
                "limit was exceeded."
            ),
        )

    total_uncompressed = 0
    total_compressed = 0
    for info in infos:
        if info.flag_bits & _ENCRYPTED_FLAG:
            raise PptxGuardError(
                reason="encrypted",
                detail="Encrypted .pptx archives are not supported.",
            )
        if _is_suspicious_path(info.filename):
            raise PptxGuardError(
                reason="suspicious_path",
                detail=(
                    "Archive contains a member with an unsafe path "
                    f"({info.filename!r})."
                ),
            )
        if info.file_size > MAX_MEMBER_UNCOMPRESSED:
            raise PptxGuardError(
                reason="member_too_large",
                detail=(
                    f"Archive part {info.filename!r} expands to "
                    f"{info.file_size} bytes, above the "
                    f"{MAX_MEMBER_UNCOMPRESSED}-byte per-part limit."
                ),
            )
        total_uncompressed += info.file_size
        total_compressed += info.compress_size
        if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
            raise PptxGuardError(
                reason="total_too_large",
                detail=(
                    f"Archive expands to more than {MAX_UNCOMPRESSED_BYTES} "
                    "bytes total."
                ),
            )

    if total_compressed > 0:
        ratio = total_uncompressed / total_compressed
        if ratio > MAX_COMPRESSION_RATIO:
            raise PptxGuardError(
                reason="ratio_too_high",
                detail=(
                    f"Archive compression ratio {ratio:.0f}:1 exceeds the "
                    f"{MAX_COMPRESSION_RATIO}:1 limit (possible zip bomb)."
                ),
            )


def _is_suspicious_path(name: str) -> bool:
    if not name:
        return True
    if name.startswith("/") or name.startswith("\\"):
        return True
    if ".." in name.replace("\\", "/").split("/"):
        return True
    # Windows drive-letter or UNC style
    if len(name) >= 2 and name[1] == ":":
        return True
    return False
