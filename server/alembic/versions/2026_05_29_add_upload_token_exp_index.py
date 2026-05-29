"""add upload token expiry index

Revision ID: 2026_05_29_upload_token_exp_index
Revises: 2026_04_30_site_tz
Create Date: 2026-05-29
"""

from alembic import op
import sqlalchemy as sa


revision = "2026_05_29_upload_token_exp_index"
down_revision = "2026_04_30_site_tz"
branch_labels = None
depends_on = None


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return index_name in {idx["name"] for idx in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_index(inspector, "upload_tokens", "ix_upload_tokens_exp"):
        op.create_index("ix_upload_tokens_exp", "upload_tokens", ["exp"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_index(inspector, "upload_tokens", "ix_upload_tokens_exp"):
        op.drop_index("ix_upload_tokens_exp", table_name="upload_tokens")
