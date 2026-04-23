"""add dashboard signup user/site tables

Revision ID: 2026_04_23_add_dashboard_signup_tables
Revises: 2026_03_18_add_site_api_keys
Create Date: 2026-04-23 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "2026_04_23_add_dashboard_signup_tables"
down_revision = "2026_03_18_add_site_api_keys"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "dashboard_users" not in tables:
        op.create_table(
            "dashboard_users",
            sa.Column("username", sa.String(length=64), primary_key=True, nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False, unique=True),
            sa.Column("password_hash", sa.Text(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index("ix_dashboard_users_email", "dashboard_users", ["email"], unique=True)

    if "dashboard_sites" not in tables:
        op.create_table(
            "dashboard_sites",
            sa.Column("site_id", sa.Text(), primary_key=True, nullable=False),
            sa.Column(
                "owner_username",
                sa.String(length=64),
                sa.ForeignKey("dashboard_users.username"),
                nullable=False,
            ),
            sa.Column("site_name", sa.String(length=255), nullable=False),
            sa.Column("allowed_origin", sa.String(length=255), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index("ix_dashboard_sites_owner", "dashboard_sites", ["owner_username"])
        op.create_index("ix_dashboard_sites_origin", "dashboard_sites", ["allowed_origin"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "dashboard_sites" in tables:
        op.drop_index("ix_dashboard_sites_origin", table_name="dashboard_sites")
        op.drop_index("ix_dashboard_sites_owner", table_name="dashboard_sites")
        op.drop_table("dashboard_sites")

    if "dashboard_users" in tables:
        op.drop_index("ix_dashboard_users_email", table_name="dashboard_users")
        op.drop_table("dashboard_users")

