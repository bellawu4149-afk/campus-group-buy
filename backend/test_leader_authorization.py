import os
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from backend import main
from backend.auth import create_access_token
from backend.database import Base, get_db
from backend.models import GroupBuy, GroupBuyProduct, Order, OrderItem, Product, User


TEST_SECRET = "leader-authorization-test-secret-only"


class LeaderAuthorizationTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        path = Path(self.temp_dir.name) / "leader_auth.db"
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
            leader = User(openid="leader-one", role="leader")
            other = User(openid="leader-two", role="leader")
            student = User(openid="student", role="student")
            newcomer = User(openid="new-leader", role="leader")
            db.add_all([leader, other, student, newcomer])
            db.flush()
            groups = [
                GroupBuy(id=101, name="我的进行中团", status="active", created_at=datetime(2026, 1, 1, 8), leader_id=leader.id),
                GroupBuy(id=102, name="我的已截团", status="closed", created_at=datetime(2026, 1, 2, 8), leader_id=leader.id),
                GroupBuy(id=201, name="其他团长团", status="active", created_at=datetime(2026, 1, 3, 8), leader_id=other.id),
                GroupBuy(id=301, name="未归属历史团", status="closed", created_at=datetime(2026, 1, 4, 8), leader_id=None),
            ]
            product = Product(id=1, name="测试商品", description="", emoji="T")
            db.add_all(groups + [product])
            db.flush()
            for group_id in (101, 102, 201, 301):
                db.add(GroupBuyProduct(group_buy_id=group_id, product_id=1, sale_price=Decimal("10.00"), display_order=1, is_active=True))
            orders = [
                (1001, 101, "OWN-ACTIVE", "001", None),
                (1002, 102, "OWN-CLOSED", "001", None),
                (2001, 201, "OTHER", "001", student.id),
                (3001, 301, "UNOWNED", "001", None),
            ]
            for order_id, group_id, order_no, follow_no, user_id in orders:
                db.add(Order(
                    id=order_id, order_no=order_no, group_buy_id=group_id,
                    group_buy_name=next(group.name for group in groups if group.id == group_id),
                    follow_no=follow_no, customer_name="联系人", customer_phone="13800000000",
                    pickup_type="dormitory", pickup_location="1", total_amount=Decimal("10.00"),
                    status="submitted", created_at=datetime(2026, 1, 5, 8), user_id=user_id,
                    items=[OrderItem(product_name="测试商品", unit_price=Decimal("10.00"), quantity=1, subtotal=Decimal("10.00"))],
                ))
            db.commit()
            self.ids = {"leader": leader.id, "other": other.id, "student": student.id, "new": newcomer.id}

    def token(self, key):
        with self.Session() as db:
            return create_access_token(db.get(User, self.ids[key]))

    def headers(self, key):
        return {"Authorization": f"Bearer {self.token(key)}"}

    def test_all_leader_routes_require_auth_and_role(self):
        routes = [
            ("GET", "/leader/group-buys", None),
            ("GET", "/leader/group-buys/101/dashboard", None),
            ("GET", "/leader/group-buys/101/orders", None),
            ("GET", "/leader/orders/1001", None),
            ("GET", "/leader/group-buys/101/config", None),
            ("POST", "/leader/group-buys/101/clone", {"name": "复制团"}),
            ("POST", "/leader/group-buys/101/close", None),
            ("GET", "/leader/group-buys/102/export.xlsx", None),
        ]
        for method, path, body in routes:
            with self.subTest(method=method, path=path, identity="none"):
                response = self.client.request(method, path, json=body)
                self.assertEqual(response.status_code, 401)
            with self.subTest(method=method, path=path, identity="student"):
                response = self.client.request(method, path, json=body, headers=self.headers("student"))
                self.assertEqual(response.status_code, 403)

    def test_owned_reads_list_details_config_and_null_user_orders(self):
        headers = self.headers("leader")
        listing = self.client.get("/leader/group-buys", headers=headers)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([row["id"] for row in listing.json()], [102, 101])
        self.assertEqual(self.client.get("/leader/group-buys/101/dashboard", headers=headers).status_code, 200)
        orders = self.client.get("/leader/group-buys/102/orders", headers=headers)
        self.assertEqual(orders.status_code, 200)
        self.assertEqual(orders.json()[0]["order_no"], "OWN-CLOSED")
        self.assertEqual(self.client.get("/leader/orders/1002", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/leader/group-buys/102/config", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/leader/group-buys/102/export.xlsx", headers=headers).status_code, 200)
        self.assertEqual(self.client.get("/leader/group-buys", headers=self.headers("new")).json(), [])

    def test_other_and_unowned_resources_are_uniform_404(self):
        headers = self.headers("leader")
        paths = [
            "/leader/group-buys/201/dashboard",
            "/leader/group-buys/301/dashboard",
            "/leader/group-buys/201/orders",
            "/leader/orders/2001",
            "/leader/orders/3001",
            "/leader/group-buys/201/config",
            "/leader/group-buys/201/export.xlsx",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path, headers=headers).status_code, 404)
        for group_id in (201, 301):
            self.assertEqual(self.client.post(f"/leader/group-buys/{group_id}/close", headers=headers).status_code, 404)
            self.assertEqual(self.client.post(f"/leader/group-buys/{group_id}/clone", json={"name": "越权复制"}, headers=headers).status_code, 404)

    def test_clone_binds_leader_and_copies_no_orders(self):
        response = self.client.post(
            "/leader/group-buys/101/clone", json={"name": "我的新团"}, headers=self.headers("leader")
        )
        self.assertEqual(response.status_code, 201)
        new_id = response.json()["group_buy"]["id"]
        with self.Session() as db:
            group = db.get(GroupBuy, new_id)
            self.assertEqual(group.leader_id, self.ids["leader"])
            self.assertEqual(db.scalars(select(Order).where(Order.group_buy_id == new_id)).all(), [])
        forged = self.client.post(
            "/leader/group-buys/101/clone",
            json={"name": "伪造团", "leader_id": self.ids["other"]},
            headers=self.headers("leader"),
        )
        self.assertEqual(forged.status_code, 422)

    def test_close_owned_group_and_old_token_loses_role_immediately(self):
        token = self.token("leader")
        headers = {"Authorization": f"Bearer {token}"}
        response = self.client.post("/leader/group-buys/101/close", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.post("/leader/group-buys/101/close", headers=headers).status_code, 409)
        with self.Session() as db:
            leader = db.get(User, self.ids["leader"])
            leader.role = "student"
            db.commit()
        self.assertEqual(self.client.get("/leader/group-buys", headers=headers).status_code, 403)


if __name__ == "__main__":
    unittest.main()
