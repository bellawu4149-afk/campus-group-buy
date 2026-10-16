from pathlib import Path
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


# 数据库文件固定保存在 backend 目录，避免从不同目录启动时生成到其他位置。
DATABASE_PATH = Path(__file__).resolve().parent / "campus_group_buy.db"
DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"

# SQLite 默认限制连接只能在创建它的线程使用；FastAPI 需要关闭这项限制。
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    """确保应用连接实际执行数据库外键约束，而不只保留约束元数据。"""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

# 每次请求使用一个独立 Session，避免不同请求共享数据库操作状态。
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """所有数据库模型共同继承的基础类。"""

    pass


def get_db() -> Generator[Session, None, None]:
    """为一次请求创建数据库 Session，并在请求结束后自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
