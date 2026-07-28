import hashlib
from pathlib import Path


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
