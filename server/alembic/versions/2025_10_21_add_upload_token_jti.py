"""add jti to upload tokens

Revision ID: 2025_10_21_add_upload_token_jti
Revises: 2025_10_20_initial
Create Date: 2024-10-21 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "2025_10_21_add_upload_token_jti"
down_revision = "2025_10_20_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("upload_tokens", sa.Column("jti", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE upload_tokens
        SET jti = md5(token_hash || COALESCE(site_id, '') || COALESCE(iat::text, ''))
        WHERE jti IS NULL
        """
    )
    op.alter_column("upload_tokens", "jti", nullable=False)
    op.create_unique_constraint("uq_upload_tokens_jti", "upload_tokens", ["jti"])
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = 'ldp_reports_default' AND c.relkind = 'r'
            ) THEN
                EXECUTE 'CREATE TABLE ldp_reports_default PARTITION OF ldp_reports DEFAULT';
            END IF;
        END;
        $$;
        """
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS ldp_reports_default")
    op.drop_constraint("uq_upload_tokens_jti", "upload_tokens", type_="unique")
    op.drop_column("upload_tokens", "jti")
