import hashlib

from app.meta.artifacts import artifact_exists, artifact_path, load_artifact, store_artifact


def test_store_artifact_returns_sha256_hex_digest(tmp_path):
    data = b"hello preview"
    digest = store_artifact(tmp_path, data)
    assert digest == hashlib.sha256(data).hexdigest()


def test_store_artifact_is_content_addressed_and_idempotent(tmp_path):
    data = b"same bytes"
    digest_a = store_artifact(tmp_path, data)
    digest_b = store_artifact(tmp_path, data)
    assert digest_a == digest_b
    assert load_artifact(tmp_path, digest_a) == data


def test_artifact_path_shards_by_digest_prefix(tmp_path):
    digest = store_artifact(tmp_path, b"x")
    path = artifact_path(tmp_path, digest)
    assert path.parent.name == digest[:2]
    assert path.name == digest


def test_artifact_exists(tmp_path):
    assert artifact_exists(tmp_path, "deadbeef") is False
    digest = store_artifact(tmp_path, b"y")
    assert artifact_exists(tmp_path, digest) is True
