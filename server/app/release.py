"""Read-only release/schema identity shared by the API and worker."""
import hashlib
from functools import lru_cache
from pathlib import Path

from alembic.script import ScriptDirectory
from sqlalchemy import text


@lru_cache(maxsize=1)
def release_identity():
    root = Path(__file__).resolve().parents[1]
    files = sorted(
        [
            *root.joinpath("app").rglob("*.py"),
            *root.joinpath("alembic").rglob("*.py"),
            root / "requirements.txt",
        ]
    )
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return {
        "code_fingerprint": digest.hexdigest(),
        "schema_heads": ScriptDirectory(str(root / "alembic")).get_heads(),
    }


async def schema_is_current(session):
    versions = set(
        (
            await session.execute(text("SELECT version_num FROM alembic_version"))
        ).scalars()
    )
    return versions == set(release_identity()["schema_heads"])


if __name__ == "__main__":
    import json

    print(json.dumps(release_identity(), sort_keys=True))
