"""Store revocable login sessions and version account mode changes."""

import sqlalchemy as sa
from alembic import op

revision = "44ac8cf0b321"
down_revision = "58fc40432bac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("mode_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "login_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=False),
        sa.Column("action_taken", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_login_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_login_sessions_token_hash")),
    )
    for column in ("id", "user_id", "expires_at"):
        op.create_index(op.f(f"ix_login_sessions_{column}"), "login_sessions", [column])


def downgrade() -> None:
    op.drop_table("login_sessions")
    op.drop_column("users", "mode_version")
