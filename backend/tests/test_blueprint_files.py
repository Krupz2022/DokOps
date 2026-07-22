import hashlib

import pytest

from app.core.blueprint_files import file_sha256, resolve_source_path


def test_resolves_path_under_root(tmp_path):
    (tmp_path / "orgs" / "acme" / "files").mkdir(parents=True)
    target = tmp_path / "orgs" / "acme" / "files" / "app.bin"
    target.write_bytes(b"x")

    assert resolve_source_path("orgs/acme/files/app.bin", tmp_path) == target.resolve()


@pytest.mark.parametrize("evil", [
    "../../etc/passwd",
    "orgs/../../../etc/shadow",
    "orgs/acme/files/../../../../../../etc/passwd",
])
def test_rejects_traversal_outside_root(tmp_path, evil):
    # rel_path comes from the DB and reaches the filesystem — escaping the root
    # must raise rather than resolve, so callers can turn it into a 403.
    with pytest.raises(ValueError):
        resolve_source_path(evil, tmp_path)


def test_rejects_absolute_path_outside_root(tmp_path):
    with pytest.raises(ValueError):
        resolve_source_path("/etc/passwd", tmp_path)


def test_size_and_mtime_columns_are_64bit():
    """Regression: these were plain `int` (int32) and Postgres rejected real values.

    mtime_ns is ~1.8e18 and artifacts can exceed 2GB — both overflow int32. SQLite
    stores them fine, so this asserts the mapped type rather than round-tripping a
    value, which is the only way to catch it without a live Postgres.
    """
    from sqlalchemy import BigInteger
    from app.models.blueprint import BlueprintSource

    cols = BlueprintSource.__table__.columns
    for name in ("size", "mtime_ns"):
        assert isinstance(cols[name].type, BigInteger), (
            f"{name} must be BIGINT; int32 overflows on real mtimes and >2GB artifacts"
        )


def test_sha256_matches_hashlib_and_streams(tmp_path):
    blob = b"\x00\xff" * 100_000
    f = tmp_path / "big.bin"
    f.write_bytes(blob)

    assert file_sha256(f) == hashlib.sha256(blob).hexdigest()
