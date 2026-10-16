import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend import main
from backend.auth import create_access_token
from backend.config import AUTH_TOKEN_ALGORITHM
from backend.database import Base, get_db
from backend.models import User
from backend.wechat import WeChatExchangeError, exchange_code_for_openid


TEST_SECRET = "unit-test-only-secret-with-sufficient-entropy"


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class WeChatAuthTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        path = Path(self.temp_dir.name) / "auth.db"
        self.engine = create_engine(
            f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False}
        )

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

        def override_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        main.app.dependency_overrides[get_db] = override_db
        self.env = patch.dict(
            os.environ,
            {
                "WECHAT_APP_ID": "test-app-id",
                "WECHAT_APP_SECRET": "test-app-secret",
                "AUTH_TOKEN_SECRET": TEST_SECRET,
            },
            clear=False,
        )
        self.env.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        main.app.dependency_overrides.clear()
        self.env.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def login(self, openid="openid-a", payload=None):
        with patch("backend.main.exchange_code_for_openid", return_value=openid):
            return self.client.post(
                "/auth/wechat/login", json=payload or {"code": "temporary-code"}
            )

    def test_exchange_valid_and_never_exposes_session_key(self):
        body = json.dumps({"openid": "wx-openid", "session_key": "private"}).encode()
        with patch("backend.wechat.urlopen", return_value=FakeResponse(body)):
            self.assertEqual(exchange_code_for_openid("code"), "wx-openid")

    def test_exchange_error_modes(self):
        cases = [
            FakeResponse(json.dumps({"errcode": 40029, "errmsg": "bad"}).encode()),
            FakeResponse(b"not-json"),
            FakeResponse(json.dumps({"session_key": "private"}).encode()),
        ]
        for response in cases:
            with self.subTest(response=response.body):
                with patch("backend.wechat.urlopen", return_value=response):
                    with self.assertRaises(WeChatExchangeError):
                        exchange_code_for_openid("code")

        from urllib.error import URLError
        for failure in (URLError("offline"), TimeoutError("timeout")):
            with self.subTest(failure=type(failure).__name__):
                with patch("backend.wechat.urlopen", side_effect=failure):
                    with self.assertRaises(WeChatExchangeError):
                        exchange_code_for_openid("code")

    def test_first_login_is_student_reuses_user_and_hides_sensitive_fields(self):
        first = self.login()
        second = self.login()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["user"]["role"], "student")
        self.assertEqual(first.json()["user"]["id"], second.json()["user"]["id"])
        serialized = json.dumps(first.json())
        for forbidden in ("openid", "session_key", "test-app-secret"):
            self.assertNotIn(forbidden, serialized)
        with self.Session() as db:
            self.assertEqual(db.query(User).count(), 1)

    def test_login_request_forbids_identity_and_role_fields(self):
        for field, value in (("role", "leader"), ("user_id", 99), ("openid", "fake"), ("session_key", "fake")):
            response = self.login(payload={"code": "code", field: value})
            self.assertEqual(response.status_code, 422)
        for code in ("", "   ", "x" * 513):
            self.assertEqual(self.login(payload={"code": code}).status_code, 422)

    def test_login_returns_valid_token_and_me_uses_database_role(self):
        response = self.login()
        token = response.json()["access_token"]
        payload = jwt.decode(token, TEST_SECRET, algorithms=[AUTH_TOKEN_ALGORITHM])
        self.assertEqual(payload["role"], "student")
        self.assertNotIn("openid", payload)
        self.assertNotIn("session_key", payload)
        self.assertNotIn("test-app-secret", json.dumps(payload))
        me = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me.status_code, 200)
        self.assertNotIn("openid", me.json())

        with self.Session() as db:
            user = db.get(User, response.json()["user"]["id"])
            user.role = "leader"
            db.commit()
        changed = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(changed.json()["role"], "leader")

    def test_me_rejects_missing_malformed_bad_expired_and_missing_user(self):
        self.assertEqual(self.client.get("/auth/me").status_code, 401)
        self.assertEqual(self.client.get("/auth/me", headers={"Authorization": "Basic abc"}).status_code, 401)
        self.assertEqual(self.client.get("/auth/me", headers={"Authorization": "Bearer bad"}).status_code, 401)

        now = datetime.now(timezone.utc)
        expired = jwt.encode(
            {"sub": "1", "role": "student", "iat": now - timedelta(days=2), "exp": now - timedelta(days=1)},
            TEST_SECRET,
            algorithm=AUTH_TOKEN_ALGORITHM,
        )
        missing = jwt.encode(
            {"sub": "999", "role": "student", "iat": now, "exp": now + timedelta(hours=1)},
            TEST_SECRET,
            algorithm=AUTH_TOKEN_ALGORITHM,
        )
        for token in (expired, missing):
            self.assertEqual(self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code, 401)

    def test_missing_secrets_fail_clearly(self):
        with patch.dict(os.environ, {"WECHAT_APP_SECRET": ""}, clear=False):
            response = self.client.post("/auth/wechat/login", json={"code": "code"})
            self.assertEqual(response.status_code, 503)
        with patch("backend.main.exchange_code_for_openid", return_value="openid-x"):
            with patch.dict(os.environ, {"AUTH_TOKEN_SECRET": ""}, clear=False):
                response = self.client.post("/auth/wechat/login", json={"code": "code"})
                self.assertEqual(response.status_code, 503)

    def test_wechat_failure_is_safe(self):
        with patch("backend.main.exchange_code_for_openid", side_effect=WeChatExchangeError("微信登录凭证无效或已过期")):
            response = self.client.post("/auth/wechat/login", json={"code": "code"})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("secret", response.text.lower())

    def test_unique_conflict_requeries_existing_user(self):
        original_commit = type(self.Session()).commit
        calls = {"count": 0}

        def conflicting_commit(session):
            if calls["count"] == 0:
                calls["count"] += 1
                other = self.Session()
                other.add(User(openid="race-openid", role="student"))
                other.commit()
                other.close()
                raise IntegrityError("insert", {}, Exception("unique"))
            return original_commit(session)

        with patch("backend.main.exchange_code_for_openid", return_value="race-openid"):
            with patch("sqlalchemy.orm.Session.commit", conflicting_commit):
                response = self.client.post("/auth/wechat/login", json={"code": "code"})
        self.assertEqual(response.status_code, 200)
        with self.Session() as db:
            self.assertEqual(db.query(User).filter(User.openid == "race-openid").count(), 1)

    def test_student_browse_stays_anonymous_while_leader_requires_auth(self):
        self.assertEqual(self.client.get("/group-buys").status_code, 200)
        self.assertEqual(self.client.get("/leader/group-buys").status_code, 401)


class RepositorySecurityTest(unittest.TestCase):
    def test_env_files_are_safe(self):
        root = Path(__file__).resolve().parents[1]
        ignore = (root / ".gitignore").read_text(encoding="utf-8")
        example = (root / "backend" / ".env.example").read_text(encoding="utf-8")
        self.assertIn("backend/.env", ignore)
        self.assertIn("WECHAT_APP_SECRET=\n", example)
        self.assertIn("AUTH_TOKEN_SECRET=\n", example)


if __name__ == "__main__":
    unittest.main()
