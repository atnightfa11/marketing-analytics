"""Password recovery and retry-safe additional-site provisioning."""
from alembic import op
import sqlalchemy as sa

revision = "2026_10_21_account_workflows"
down_revision = "2026_10_01_capacity_requests"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "dashboard_users",
        sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "password_resets",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "username",
            sa.String(64),
            sa.ForeignKey("dashboard_users.username"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_password_resets_username", "password_resets", ["username"])
    op.create_index("ix_password_resets_expires_at", "password_resets", ["expires_at"])
    op.create_table(
        "site_provisioning",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column(
            "owner_username",
            sa.String(64),
            sa.ForeignKey("dashboard_users.username"),
            nullable=False,
        ),
        sa.Column("site_id", sa.String(), nullable=False, unique=True),
        sa.Column("site_name", sa.String(255), nullable=False),
        sa.Column("allowed_origin", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("subscription_id", sa.String()),
        sa.Column("extra_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_site_provisioning_pending",
        "site_provisioning",
        ["owner_username"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )


def downgrade():
    op.drop_table("site_provisioning")
    op.drop_table("password_resets")
    op.drop_column("dashboard_users", "auth_version")
