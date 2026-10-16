"""normalize orders group buy foreign key

Revision ID: 892d97069028
Revises: c5ef3e44665e
Create Date: 2026-10-03 19:57:21.626516+08:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '892d97069028'
down_revision: Union[str, Sequence[str], None] = 'c5ef3e44665e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Map legacy group names to real IDs, then rebuild orders safely."""
    connection = op.get_bind()
    order_count_before = connection.scalar(sa.text("SELECT COUNT(*) FROM orders"))

    foreign_key_errors = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise RuntimeError(f"Existing foreign key errors prevent migration: {foreign_key_errors}")

    legacy_rows = connection.execute(
        sa.text(
            "SELECT id, group_buy_id, group_buy_name "
            "FROM orders ORDER BY id"
        )
    ).mappings().all()

    name_to_id: dict[str, int] = {}
    for row in legacy_rows:
        legacy_id = row["group_buy_id"]
        group_name = row["group_buy_name"]
        if not legacy_id or not group_name or legacy_id != group_name:
            raise RuntimeError(
                f"Order {row['id']} has inconsistent legacy group fields; migration aborted"
            )

        matches = connection.execute(
            sa.text("SELECT id FROM group_buys WHERE name = :name ORDER BY id"),
            {"name": group_name},
        ).scalars().all()
        if len(matches) != 1:
            raise RuntimeError(
                f"Order {row['id']} group name {group_name!r} matched "
                f"{len(matches)} group_buys rows; exactly one is required"
            )
        name_to_id[group_name] = matches[0]

    op.add_column(
        "orders",
        sa.Column("group_buy_id_new", sa.Integer(), nullable=True),
    )

    for group_name, group_buy_id in name_to_id.items():
        connection.execute(
            sa.text(
                "UPDATE orders SET group_buy_id_new = :group_buy_id "
                "WHERE group_buy_name = :group_name "
                "AND group_buy_id = :legacy_group_buy_id"
            ),
            {
                "group_buy_id": group_buy_id,
                "group_name": group_name,
                "legacy_group_buy_id": group_name,
            },
        )

    null_count = connection.scalar(
        sa.text("SELECT COUNT(*) FROM orders WHERE group_buy_id_new IS NULL")
    )
    missing_target_count = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM orders AS o "
            "LEFT JOIN group_buys AS g ON g.id = o.group_buy_id_new "
            "WHERE g.id IS NULL"
        )
    )
    order_count_after_mapping = connection.scalar(sa.text("SELECT COUNT(*) FROM orders"))
    if null_count != 0 or missing_target_count != 0:
        raise RuntimeError("Not every order mapped to an existing group_buys row")
    if order_count_after_mapping != order_count_before:
        raise RuntimeError("Order row count changed during mapping")

    original_foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
    if original_foreign_keys:
        with op.get_context().autocommit_block():
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        if connection.exec_driver_sql("PRAGMA foreign_keys").scalar() != 0:
            raise RuntimeError("Could not disable SQLite foreign key enforcement for batch rebuild")

    try:
        with op.batch_alter_table("orders", recreate="always") as batch_op:
            batch_op.drop_column("group_buy_id")
            batch_op.create_foreign_key(
                "fk_orders_group_buy_id_group_buys",
                "group_buys",
                ["group_buy_id_new"],
                ["id"],
            )
            batch_op.alter_column(
                "group_buy_id_new",
                new_column_name="group_buy_id",
                existing_type=sa.Integer(),
                nullable=False,
            )
    finally:
        if original_foreign_keys:
            with op.get_context().autocommit_block():
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")

    if connection.scalar(sa.text("SELECT COUNT(*) FROM orders")) != order_count_before:
        raise RuntimeError("Order row count changed during batch rebuild")
    foreign_key_errors = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise RuntimeError(f"Foreign key errors after migration: {foreign_key_errors}")


def downgrade() -> None:
    """Restore the legacy string field from the preserved name snapshot."""
    connection = op.get_bind()
    order_count_before = connection.scalar(sa.text("SELECT COUNT(*) FROM orders"))

    invalid_name_count = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM orders "
            "WHERE group_buy_name IS NULL OR group_buy_name = '' "
            "OR length(group_buy_name) > 100"
        )
    )
    if invalid_name_count != 0:
        raise RuntimeError("Cannot restore legacy group_buy_id from group_buy_name")

    op.add_column(
        "orders",
        sa.Column("group_buy_id_old", sa.String(length=100), nullable=True),
    )
    connection.execute(
        sa.text("UPDATE orders SET group_buy_id_old = group_buy_name")
    )
    if connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM orders "
            "WHERE group_buy_id_old IS NULL OR group_buy_id_old = ''"
        )
    ) != 0:
        raise RuntimeError("Legacy group_buy_id restoration left invalid values")
    if connection.scalar(sa.text("SELECT COUNT(*) FROM orders")) != order_count_before:
        raise RuntimeError("Order row count changed while preparing downgrade")

    original_foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
    if original_foreign_keys:
        with op.get_context().autocommit_block():
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        if connection.exec_driver_sql("PRAGMA foreign_keys").scalar() != 0:
            raise RuntimeError("Could not disable SQLite foreign key enforcement for batch rebuild")

    try:
        with op.batch_alter_table("orders", recreate="always") as batch_op:
            batch_op.drop_constraint(
                "fk_orders_group_buy_id_group_buys",
                type_="foreignkey",
            )
            batch_op.drop_column("group_buy_id")
            batch_op.alter_column(
                "group_buy_id_old",
                new_column_name="group_buy_id",
                existing_type=sa.String(length=100),
                nullable=False,
            )
    finally:
        if original_foreign_keys:
            with op.get_context().autocommit_block():
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")

    if connection.scalar(sa.text("SELECT COUNT(*) FROM orders")) != order_count_before:
        raise RuntimeError("Order row count changed during downgrade rebuild")
    foreign_key_errors = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise RuntimeError(f"Foreign key errors after downgrade: {foreign_key_errors}")
