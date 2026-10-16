import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from backend import main
from backend.auth import create_access_token
from backend.config import AUTH_TOKEN_ALGORITHM
from backend.database import Base, get_db
from backend.models import GroupBuy, GroupBuyProduct, Order, OrderItem, Product, User


TEST_SECRET = "student-order-ownership-test-secret-only"


class StudentOrderOwnershipTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        path = Path(self.temp_dir.name) / "student_orders.db"
        self.engine = create_engine(
            f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False}
        )

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._seed()

        def override_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        main.app.dependency_overrides[get_db] = override_db
        self.env = patch.dict(os.environ, {"AUTH_TOKEN_SECRET": TEST_SECRET}, clear=False)
        self.env.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.clear()
        self.env.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _seed(self):
        with self.Session() as db:
            self.student = User(openid="student-openid", role="student")
            self.other = User(openid="other-openid", role="student")
            self.leader = User(openid="leader-openid", role="leader")
            active = GroupBuy(id=1, name="开放团", status="active", created_at=datetime(2026, 1, 1, 8))
            closed = GroupBuy(id=2, name="已截团", status="closed", created_at=datetime(2026, 1, 2, 8))
            product = Product(id=1, name="面包", description="", emoji="B")
            db.add_all([self.student, self.other, self.leader, active, closed, product])
            db.flush()
            db.add(GroupBuyProduct(group_buy_id=1, product_id=1, sale_price=Decimal("12.80"), display_order=1, is_active=True))
            db.add_all([
                Order(
                    order_no="HISTORY-NULL", group_buy_id=2, group_buy_name="已截团", follow_no="001",
                    customer_name="历史用户", customer_phone="13000000000", pickup_type="other", pickup_location="旧地点",
                    total_amount=Decimal("8.00"), status="submitted", created_at=datetime(2026, 1, 2, 9), user_id=None,
                    items=[OrderItem(product_name="旧商品", unit_price=Decimal("8.00"), quantity=1, subtotal=Decimal("8.00"))],
                ),
                Order(
                    order_no="OTHER-USER", group_buy_id=2, group_buy_name="已截团", follow_no="002",
                    customer_name="同名学生", customer_phone="13800000000", pickup_type="dormitory", pickup_location="2",
                    total_amount=Decimal("9.00"), status="submitted", created_at=datetime(2026, 1, 3, 9), user_id=self.other.id,
                    items=[OrderItem(product_name="他人商品", unit_price=Decimal("9.00"), quantity=1, subtotal=Decimal("9.00"))],
                ),
                Order(
                    order_no="CURRENT-CLOSED", group_buy_id=2, group_buy_name="已截团", follow_no="003",
                    customer_name="当前学生", customer_phone="13800000000", pickup_type="other", pickup_location="北门",
                    total_amount=Decimal("10.00"), status="submitted", created_at=datetime(2026, 1, 4, 9), user_id=self.student.id,
                    items=[OrderItem(product_name="历史已绑定商品", unit_price=Decimal("10.00"), quantity=1, subtotal=Decimal("10.00"))],
                ),
            ])
            db.commit()
            self.student_id = self.student.id
            self.other_id = self.other.id
            self.leader_id = self.leader.id

    def token_for(self, user_id):
        with self.Session() as db:
            return create_access_token(db.get(User, user_id))

    def auth(self, user_id=None):
        return {"Authorization": f"Bearer {self.token_for(user_id or self.student_id)}"}

    def payload(self, **extra):
        result = {
            "group_buy_id": 1,
            "customer_name": "同名学生",
            "customer_phone": "13800000000",
            "pickup_type": "dormitory",
            "pickup_location": "3",
            "items": [{"product_id": 1, "quantity": 2}],
        }
        result.update(extra)
        return result

    def order_state(self):
        with self.Session() as db:
            return (
                db.scalar(select(func.count(Order.id))),
                db.scalar(select(func.max(Order.follow_no)).where(Order.group_buy_id == 1)),
            )

    def test_missing_invalid_and_expired_tokens_create_nothing(self):
        now = datetime.now(timezone.utc)
        expired = jwt.encode(
            {"sub": str(self.student_id), "role": "student", "iat": now - timedelta(days=2), "exp": now - timedelta(days=1)},
            TEST_SECRET,
            algorithm=AUTH_TOKEN_ALGORITHM,
        )
        before = self.order_state()
        responses = [
            self.client.post("/orders", json=self.payload()),
            self.client.post("/orders", json=self.payload(), headers={"Authorization": "Bearer invalid"}),
            self.client.post("/orders", json=self.payload(), headers={"Authorization": f"Bearer {expired}"}),
        ]
        self.assertEqual([response.status_code for response in responses], [401, 401, 401])
        self.assertEqual(self.order_state(), before)

    def test_student_and_leader_orders_bind_server_authenticated_user(self):
        first = self.client.post("/orders", json=self.payload(), headers=self.auth())
        second = self.client.post("/orders", json=self.payload(customer_name="团长消费者"), headers=self.auth(self.leader_id))
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual((first.json()["follow_no"], second.json()["follow_no"]), ("001", "002"))
        with self.Session() as db:
            self.assertEqual(db.get(Order, first.json()["order_id"]).user_id, self.student_id)
            self.assertEqual(db.get(Order, second.json()["order_id"]).user_id, self.leader_id)

    def test_client_cannot_forge_ownership_or_server_fields(self):
        forbidden = {
            "user_id": self.other_id,
            "openid": "forged",
            "role": "leader",
            "follow_no": "999",
            "order_no": "FORGED",
            "total_amount": "0.01",
            "status": "paid",
        }
        for field, value in forbidden.items():
            with self.subTest(field=field):
                response = self.client.post("/orders", json=self.payload(**{field: value}), headers=self.auth())
                self.assertEqual(response.status_code, 422)

    def test_mine_only_returns_current_user_with_items_and_ordering(self):
        older = self.client.post("/orders", json=self.payload(), headers=self.auth())
        newer = self.client.post("/orders", json=self.payload(customer_name="新订单"), headers=self.auth())
        self.assertEqual((older.status_code, newer.status_code), (201, 201))
        response = self.client.get("/orders/mine", headers=self.auth())
        self.assertEqual(response.status_code, 200)
        rows = response.json()
        self.assertEqual([row["id"] for row in rows[:2]], [newer.json()["order_id"], older.json()["order_id"]])
        self.assertEqual(rows[2]["order_no"], "CURRENT-CLOSED")
        self.assertEqual(rows[2]["group_buy_name"], "已截团")
        self.assertEqual(rows[0]["items"][0]["product_name"], "面包")
        self.assertEqual(rows[0]["items"][0]["quantity"], 2)
        self.assertNotIn("OTHER-USER", [row["order_no"] for row in rows])
        self.assertNotIn("HISTORY-NULL", [row["order_no"] for row in rows])
        self.assertEqual(self.client.get("/orders/mine").status_code, 401)

    def test_closed_group_rejected_without_order_or_follow_number(self):
        before = self.order_state()
        response = self.client.post("/orders", json=self.payload(group_buy_id=2), headers=self.auth())
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.order_state(), before)


if __name__ == "__main__":
    unittest.main()
