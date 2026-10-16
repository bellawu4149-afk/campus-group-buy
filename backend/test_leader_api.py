from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.database import Base
from backend.main import (
    get_leader_dashboard,
    get_leader_order,
    list_leader_orders,
)
from backend.models import GroupBuy, Order, OrderItem, User


class LeaderApiTest(unittest.TestCase):
    """使用独立临时数据库验证团长只读查询，不接触正式订单。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "leader_test.db"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self._seed()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _seed(self) -> None:
        self.leader = User(id=100, openid="leader-api-test", role="leader")
        active = GroupBuy(
            id=1,
            name="测试团",
            status="active",
            created_at=datetime(2026, 1, 1, 8, 0),
            leader_id=100,
        )
        closed = GroupBuy(
            id=2,
            name="历史空团",
            status="closed",
            created_at=datetime(2025, 12, 1, 8, 0),
            leader_id=100,
        )
        self.db.add_all([self.leader, active, closed])
        self.db.flush()
        moments = [
            datetime(2026, 1, 2, 8, 0),
            datetime(2026, 1, 3, 8, 0),
            datetime(2026, 1, 4, 8, 0),
            datetime(2026, 1, 4, 8, 0),
        ]
        specifications = [
            ("001", "未填写", None, None, None, Decimal("6.00")),
            ("002", "甲", "13000000000", "dormitory", "10", Decimal("8.00")),
            ("003", "乙", "13100000000", "dormitory", "2", Decimal("2.00")),
            ("004", "丙", "13200000000", "other", "图书馆", Decimal("12.00")),
        ]
        item_specs = [
            [("商品A", "2.00", 3, "6.00")],
            [("商品A", "2.50", 2, "5.00"), ("商品B", "3.00", 1, "3.00")],
            [("商品A", "2.00", 1, "2.00")],
            [("商品B", "3.00", 4, "12.00")],
        ]
        for index, (spec, items) in enumerate(zip(specifications, item_specs), start=1):
            follow_no, name, phone, pickup_type, location, total = spec
            order = Order(
                id=index,
                order_no=f"TEST{index}",
                group_buy_id=1,
                group_buy_name="测试团",
                follow_no=follow_no,
                customer_name=name,
                customer_phone=phone,
                pickup_type=pickup_type,
                pickup_location=location,
                total_amount=total,
                status="submitted",
                created_at=moments[index - 1],
                items=[
                    OrderItem(
                        product_name=product_name,
                        unit_price=Decimal(unit_price),
                        quantity=quantity,
                        subtotal=Decimal(subtotal),
                    )
                    for product_name, unit_price, quantity, subtotal in items
                ],
            )
            self.db.add(order)
        self.db.commit()

    def test_dashboard_aggregates_snapshots_pickups_and_money(self) -> None:
        dashboard = get_leader_dashboard(1, self.db, self.leader)
        self.assertEqual(dashboard.summary.order_count, 4)
        self.assertEqual(dashboard.summary.item_count, 11)
        self.assertEqual(dashboard.summary.total_amount, "28.00")
        self.assertEqual(
            [row.model_dump() for row in dashboard.product_summary],
            [
                {"product_name": "商品A", "quantity": 6, "amount": "13.00"},
                {"product_name": "商品B", "quantity": 5, "amount": "15.00"},
            ],
        )
        self.assertEqual(
            [row.location for row in dashboard.pickup_summary.dormitory],
            ["2", "10"],
        )
        self.assertEqual(
            dashboard.pickup_summary.dormitory[0].model_dump(),
            {"location": "2", "order_count": 1, "item_count": 1},
        )
        self.assertEqual(
            dashboard.pickup_summary.other[0].model_dump(),
            {"location": "图书馆", "order_count": 1, "item_count": 4},
        )
        self.assertEqual(
            dashboard.pickup_summary.unknown.model_dump(),
            {"order_count": 1, "item_count": 3},
        )

    def test_orders_are_sorted_and_include_quantity_totals_and_nulls(self) -> None:
        orders = list_leader_orders(1, self.db, self.leader)
        self.assertEqual([order.id for order in orders], [4, 3, 2, 1])
        self.assertEqual([order.item_count for order in orders], [4, 1, 3, 3])
        historical = orders[-1]
        self.assertIsNone(historical.customer_phone)
        self.assertIsNone(historical.pickup_type)
        self.assertIsNone(historical.pickup_location)

    def test_order_detail_returns_snapshot_items(self) -> None:
        detail = get_leader_order(2, self.db, self.leader)
        self.assertEqual(detail.group_buy_name, "测试团")
        self.assertEqual(detail.total_amount, "8.00")
        self.assertEqual(
            [item.model_dump() for item in detail.items],
            [
                {"product_name": "商品A", "unit_price": "2.50", "quantity": 2, "subtotal": "5.00"},
                {"product_name": "商品B", "unit_price": "3.00", "quantity": 1, "subtotal": "3.00"},
            ],
        )

    def test_missing_resources_return_404(self) -> None:
        with self.assertRaises(HTTPException) as group_error:
            get_leader_dashboard(999, self.db, self.leader)
        self.assertEqual(group_error.exception.status_code, 404)
        self.assertEqual(group_error.exception.detail, "团购不存在或无权访问")
        with self.assertRaises(HTTPException) as order_error:
            get_leader_order(999, self.db, self.leader)
        self.assertEqual(order_error.exception.status_code, 404)
        self.assertEqual(order_error.exception.detail, "订单不存在或无权访问")

    def test_closed_empty_group_is_readable(self) -> None:
        dashboard = get_leader_dashboard(2, self.db, self.leader)
        self.assertEqual(dashboard.group_buy.status, "closed")
        self.assertEqual(dashboard.summary.model_dump(), {
            "order_count": 0,
            "item_count": 0,
            "total_amount": "0.00",
        })
        self.assertEqual(dashboard.product_summary, [])
        self.assertEqual(dashboard.pickup_summary.dormitory, [])
        self.assertEqual(dashboard.pickup_summary.other, [])

    def test_queries_do_not_modify_orders(self) -> None:
        before = [
            tuple(row)
            for row in self.db.execute(
                select(Order.id, Order.order_no, Order.total_amount, Order.status)
                .order_by(Order.id)
            ).all()
        ]
        get_leader_dashboard(1, self.db, self.leader)
        list_leader_orders(1, self.db, self.leader)
        get_leader_order(1, self.db, self.leader)
        after = [
            tuple(row)
            for row in self.db.execute(
                select(Order.id, Order.order_no, Order.total_amount, Order.status)
                .order_by(Order.id)
            ).all()
        ]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
