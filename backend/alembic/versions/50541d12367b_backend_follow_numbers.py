"""backend follow numbers

Revision ID: 50541d12367b
Revises: f88ba0bf56a1
Create Date: 2026-10-03 21:34:42.340946+08:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '50541d12367b'
down_revision: Union[str, Sequence[str], None] = 'f88ba0bf56a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Backfill stable per-group numbers, then enforce uniqueness."""
    connection = op.get_bind()
    order_count_before = connection.scalar(sa.text("SELECT COUNT(*) FROM orders"))
    foreign_key_errors = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise RuntimeError(f"Existing foreign key errors prevent migration: {foreign_key_errors}")

    rows = connection.execute(
        sa.text(
            "SELECT id, group_buy_id FROM orders "
            "ORDER BY group_buy_id ASC, created_at ASC, id ASC"
        )
    ).mappings().all()
    sequence_by_group: dict[int, int] = {}
    for row in rows:
        group_buy_id = row["group_buy_id"]
        sequence = sequence_by_group.get(group_buy_id, 0) + 1
        sequence_by_group[group_buy_id] = sequence
        connection.execute(
            sa.text("UPDATE orders SET follow_no = :follow_no WHERE id = :order_id"),
            {"follow_no": f"{sequence:03d}", "order_id": row["id"]},
        )

    invalid_groups = connection.execute(
        sa.text(
            "SELECT group_buy_id FROM orders GROUP BY group_buy_id "
            "HAVING COUNT(*) != COUNT(DISTINCT follow_no) "
            "OR SUM(CASE WHEN follow_no IS NULL OR follow_no = '' "
            "THEN 1 ELSE 0 END) != 0"
        )
    ).fetchall()
    if invalid_groups:
        raise RuntimeError(f"Follow number backfill validation failed: {invalid_groups}")
    if connection.scalar(sa.text("SELECT COUNT(*) FROM orders")) != order_count_before:
        raise RuntimeError("Order row count changed during follow number backfill")

    original_foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
    if original_foreign_keys:
        with op.get_context().autocommit_block():
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        if connection.exec_driver_sql("PRAGMA foreign_keys").scalar() != 0:
            raise RuntimeError("Could not disable SQLite foreign keys for orders rebuild")

    try:
        with op.batch_alter_table("orders", recreate="always") as batch_op:
            batch_op.create_unique_constraint(
                "uq_orders_group_buy_follow_no",
                ["group_buy_id", "follow_no"],
            )
    finally:
        if original_foreign_keys:
            with op.get_context().autocommit_block():
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")

    if connection.scalar(sa.text("SELECT COUNT(*) FROM orders")) != order_count_before:
        raise RuntimeError("Order row count changed during orders rebuild")
    foreign_key_errors = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise RuntimeError(f"Foreign key errors after migration: {foreign_key_errors}")


def downgrade() -> None:
    """Remove uniqueness and restore the legacy pending placeholder."""
    connection = op.get_bind()
    order_count_before = connection.scalar(sa.text("SELECT COUNT(*) FROM orders"))
    original_foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
    if original_foreign_keys:
        with op.get_context().autocommit_block():
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        if connection.exec_driver_sql("PRAGMA foreign_keys").scalar() != 0:
            raise RuntimeError("Could not disable SQLite foreign keys for orders rebuild")

    try:
        with op.batch_alter_table("orders", recreate="always") as batch_op:
            batch_op.drop_constraint(
                "uq_orders_group_buy_follow_no",
                type_="unique",
            )
    finally:
        if original_foreign_keys:
            with op.get_context().autocommit_block():
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")

    connection.execute(sa.text("UPDATE orders SET follow_no = 'pending'"))
    if connection.scalar(sa.text("SELECT COUNT(*) FROM orders")) != order_count_before:
        raise RuntimeError("Order row count changed during downgrade")
    foreign_key_errors = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise RuntimeError(f"Foreign key errors after downgrade: {foreign_key_errors}")
