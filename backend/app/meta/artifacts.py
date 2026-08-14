import hashlib
import re
from pathlib import Path

#: Every artifact this store writes is named by its sha256 hexdigest (see
#: `store_artifact`), so a value of any other shape was never produced here.
#: A caller that takes a digest from an untrusted source -- the
#: `{artifact_hash}` URL segment on `GET /meta/preview` is the only one --
#: checks `is_stored_digest` first, so a caller-supplied value can never steer
#: the join in `artifact_path` outside `root`.
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def is_stored_digest(digest: str) -> bool:
    """Whether `digest` has the shape `store_artifact` produces."""
    return isinstance(digest, str) and _SHA256_HEX.fullmatch(digest) is not None


def artifact_path(root: Path, digest: str) -> Path:
    return Path(root) / digest[:2] / digest


def artifact_exists(root: Path, digest: str) -> bool:
    return artifact_path(root, digest).exists()


def store_artifact(root: Path, data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()
    path = artifact_path(root, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(data)
    return digest


def load_artifact(root: Path, digest: str) -> bytes:
    return artifact_path(root, digest).read_bytes()
