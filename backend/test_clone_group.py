from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.database import Base
from backend.main import (
    clone_leader_group_buy,
    create_order,
    get_leader_dashboard,
    get_leader_group_buy_config,
    list_group_buys,
    list_leader_group_buys,
    list_leader_orders,
)
from backend.models import GroupBuy, GroupBuyProduct, Order, OrderItem, Product, User
from backend.schemas import LeaderGroupBuyCloneCreate, OrderCreate


class CloneGroupTest(unittest.TestCase):
    """复制新团测试只使用隔离临时库，不接触正式 group_buy_id=1。"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "clone_group_test.db"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self._seed()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _seed(self) -> None:
        self.current_user = User(id=1, openid="clone-test-user", role="leader")
        self.db.add_all([
            self.current_user,
            GroupBuy(id=201, name="active 来源团", status="active", created_at=datetime(2026, 1, 1, 8), leader_id=1),
            GroupBuy(id=202, name="closed 来源团", status="closed", created_at=datetime(2026, 1, 2, 8), leader_id=1),
            GroupBuy(id=203, name="空商品来源团", status="closed", created_at=datetime(2026, 1, 3, 8), leader_id=1),
            Product(id=301, name="商品甲", description="甲", emoji="A"),
            Product(id=302, name="商品乙", description="乙", emoji="B"),
            Product(id=303, name="商品丙", description="丙", emoji="C"),
        ])
        self.db.flush()
        self.db.add_all([
            GroupBuyProduct(group_buy_id=201, product_id=301, sale_price=Decimal("12.80"), display_order=2, is_active=True, last_week_sales=68),
            GroupBuyProduct(group_buy_id=201, product_id=302, sale_price=Decimal("15.80"), display_order=1, is_active=False, last_week_sales=51),
            GroupBuyProduct(group_buy_id=201, product_id=303, sale_price=Decimal("18.80"), display_order=3, is_active=True, last_week_sales=43),
            GroupBuyProduct(group_buy_id=202, product_id=301, sale_price=Decimal("13.50"), display_order=1, is_active=True, last_week_sales=70),
        ])
        self.db.add(
            Order(
                id=401,
                order_no="SOURCE001",
                group_buy_id=201,
                group_buy_name="active 来源团",
                follow_no="001",
                customer_name="来源订单",
                customer_phone="13800000000",
                pickup_type="dormitory",
                pickup_location="1",
                total_amount=Decimal("12.80"),
                status="submitted",
                created_at=datetime(2026, 1, 4, 8),
                items=[OrderItem(product_name="商品甲", unit_price=Decimal("12.80"), quantity=1, subtotal=Decimal("12.80"))],
            )
        )
        self.db.commit()

    def _clone(self, source_id: int = 201, name: str = "  新一期团购  "):
        return clone_leader_group_buy(
            source_id,
            LeaderGroupBuyCloneCreate(name=name),
            self.db,
            self.current_user,
        )

    def _order_payload(self, group_buy_id: int) -> OrderCreate:
        return OrderCreate.model_validate({
            "group_buy_id": group_buy_id,
            "customer_name": "新团同学",
            "customer_phone": "13900000000",
            "pickup_type": "other",
            "pickup_location": "北门取货点",
            "items": [{"product_id": 301, "quantity": 1}],
        })

    def test_active_clone_copies_only_configuration(self) -> None:
        before = {
            "groups": self.db.scalar(select(func.count(GroupBuy.id))),
            "products": self.db.scalar(select(func.count(Product.id))),
            "links": self.db.scalar(select(func.count(GroupBuyProduct.id))),
            "orders": self.db.scalar(select(func.count(Order.id))),
            "items": self.db.scalar(select(func.count(OrderItem.id))),
        }
        source_links = self.db.scalars(
            select(GroupBuyProduct).where(GroupBuyProduct.group_buy_id == 201).order_by(GroupBuyProduct.id)
        ).all()
        result = self._clone()
        new_id = result.group_buy.id
        self.assertEqual(result.status, "success")
        self.assertEqual(result.group_buy.name, "新一期团购")
        self.assertEqual(result.group_buy.status, "active")
        self.assertEqual(result.product_count, 3)
        self.assertEqual(self.db.scalar(select(func.count(GroupBuy.id))), before["groups"] + 1)
        self.assertEqual(self.db.scalar(select(func.count(Product.id))), before["products"])
        self.assertEqual(self.db.scalar(select(func.count(GroupBuyProduct.id))), before["links"] + 3)
        self.assertEqual(self.db.scalar(select(func.count(Order.id))), before["orders"])
        self.assertEqual(self.db.scalar(select(func.count(OrderItem.id))), before["items"])

        new_links = self.db.scalars(
            select(GroupBuyProduct).where(GroupBuyProduct.group_buy_id == new_id).order_by(GroupBuyProduct.product_id)
        ).all()
        source_by_product = {link.product_id: link for link in source_links}
        self.assertEqual({link.product_id for link in new_links}, set(source_by_product))
        for link in new_links:
            source = source_by_product[link.product_id]
            self.assertNotEqual(link.id, source.id)
            self.assertEqual(link.sale_price, source.sale_price)
            self.assertEqual(link.display_order, source.display_order)
            self.assertEqual(link.is_active, source.is_active)
            self.assertEqual(link.last_week_sales, source.last_week_sales)

        dashboard = get_leader_dashboard(new_id, self.db, self.current_user)
        self.assertEqual(dashboard.summary.model_dump(), {"order_count": 0, "item_count": 0, "total_amount": "0.00"})
        self.assertEqual(list_leader_orders(new_id, self.db, self.current_user), [])

    def test_leader_group_buy_list_aggregates_and_sorts_without_dashboard_calls(self) -> None:
        group_202 = self.db.get(GroupBuy, 202)
        group_202.created_at = self.db.get(GroupBuy, 203).created_at
        self.db.commit()
        rows = list_leader_group_buys(self.db, self.current_user)
        self.assertEqual([row.id for row in rows], [203, 202, 201])
        by_id = {row.id: row for row in rows}
        self.assertEqual(by_id[201].status, "active")
        self.assertEqual(by_id[202].status, "closed")
        self.assertEqual(by_id[201].order_count, 1)
        self.assertEqual(by_id[201].item_count, 1)
        self.assertEqual(by_id[201].total_amount, "12.80")
        self.assertEqual(by_id[201].product_count, 3)
        self.assertEqual(by_id[202].product_count, 1)
        self.assertEqual(by_id[203].product_count, 0)

    def test_student_group_buy_list_returns_all_and_only_active_groups(self) -> None:
        self.assertEqual([row.id for row in list_group_buys(False, self.db)], [201])
        self.db.get(GroupBuy, 202).status = "active"
        self.db.commit()
        self.assertEqual([row.id for row in list_group_buys(False, self.db)], [201, 202])
        self.db.get(GroupBuy, 201).status = "closed"
        self.db.get(GroupBuy, 202).status = "closed"
        self.db.commit()
        self.assertEqual(list_group_buys(False, self.db), [])

    def test_closed_source_and_empty_source_clone(self) -> None:
        closed_result = self._clone(202, "closed 复制团")
        self.assertEqual(closed_result.group_buy.status, "active")
        self.assertEqual(closed_result.product_count, 1)
        empty_result = self._clone(203, "空商品复制团")
        self.assertEqual(empty_result.product_count, 0)
        self.assertEqual(get_leader_group_buy_config(empty_result.group_buy.id, self.db, self.current_user).products, [])

    def test_name_validation_and_missing_source(self) -> None:
        for name in ["", "   ", "超" * 101]:
            with self.assertRaises(ValidationError):
                LeaderGroupBuyCloneCreate(name=name)
        with self.assertRaises(ValidationError):
            LeaderGroupBuyCloneCreate.model_validate({"name": "合法名称", "status": "closed"})
        with self.assertRaises(HTTPException) as error:
            self._clone(999, "不存在来源")
        self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(error.exception.detail, "团购不存在或无权访问")

    def test_new_group_follow_numbers_start_independently(self) -> None:
        result = self._clone(201, "独立编号团")
        new_id = result.group_buy.id
        first = create_order(self._order_payload(new_id), self.db, self.current_user)
        second = create_order(self._order_payload(new_id), self.db, self.current_user)
        self.assertEqual((first.follow_no, second.follow_no), ("001", "002"))
        self.assertEqual(
            self.db.scalar(select(func.max(Order.follow_no)).where(Order.group_buy_id == 201)),
            "001",
        )
        self.assertEqual(
            self.db.scalar(select(func.count(Order.id)).where(Order.group_buy_id == new_id, Order.follow_no == "001")),
            1,
        )
        self.assertEqual(
            self.db.scalar(select(func.count(Order.id)).where(Order.group_buy_id == 201, Order.follow_no == "001")),
            1,
        )

    def test_mid_clone_failure_rolls_back_group_and_links(self) -> None:
        before_groups = self.db.scalar(select(func.count(GroupBuy.id)))
        before_links = self.db.scalar(select(func.count(GroupBuyProduct.id)))
        insert_count = 0

        def fail_second_link(mapper, connection, target):
            nonlocal insert_count
            if target.group_buy_id not in (201, 202, 203):
                insert_count += 1
                if insert_count == 2:
                    raise SQLAlchemyError("simulated clone failure")

        event.listen(GroupBuyProduct, "before_insert", fail_second_link)
        try:
            with self.assertRaises(HTTPException) as error:
                self._clone(201, "应该回滚的团")
            self.assertEqual(error.exception.status_code, 500)
            self.assertEqual(error.exception.detail, "复制团购失败")
        finally:
            event.remove(GroupBuyProduct, "before_insert", fail_second_link)
        self.assertEqual(self.db.scalar(select(func.count(GroupBuy.id))), before_groups)
        self.assertEqual(self.db.scalar(select(func.count(GroupBuyProduct.id))), before_links)
        self.assertIsNone(self.db.scalar(select(GroupBuy).where(GroupBuy.name == "应该回滚的团")))


if __name__ == "__main__":
    unittest.main()
