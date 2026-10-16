from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .time_utils import now_in_shanghai


class User(Base):
    """微信身份接入前的最小用户与角色数据基础。"""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('student', 'leader')", name="ck_users_role"),
        UniqueConstraint("openid", name="uq_users_openid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    openid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    nickname: Mapped[str | None] = mapped_column(String(100), nullable=True)
    role: Mapped[str] = mapped_column(
        String(20),
        default="student",
        server_default="student",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_in_shanghai,
        nullable=False,
    )

    orders: Mapped[list[Order]] = relationship(
        back_populates="user",
        passive_deletes="all",
    )
    group_buys: Mapped[list[GroupBuy]] = relationship(
        back_populates="leader",
        passive_deletes="all",
    )


class Feedback(Base):
    """用户反馈表。"""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    overall_experience: Mapped[str] = mapped_column(String(50), nullable=False)
    convenience: Mapped[str] = mapped_column(String(50), nullable=False)
    ranking_helpful: Mapped[str] = mapped_column(String(50), nullable=False)
    continue_use: Mapped[str] = mapped_column(String(50), nullable=False)

    # V2 原型阶段用普通文本保存多个选项，例如“订单提醒, 新品推荐”。
    desired_features: Mapped[str | None] = mapped_column(Text, nullable=True)
    service_satisfaction: Mapped[int] = mapped_column(Integer, nullable=False)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_in_shanghai,
        nullable=False,
    )


class GroupBuy(Base):
    """团购活动表。旧订单关联将在后续独立阶段处理。"""

    __tablename__ = "group_buys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        default="active",
        server_default="active",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_in_shanghai,
        nullable=False,
    )
    leader_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", name="fk_group_buys_leader_id_users"),
        nullable=True,
        index=True,
    )

    orders: Mapped[list[Order]] = relationship(back_populates="group_buy")
    product_links: Mapped[list[GroupBuyProduct]] = relationship(
        back_populates="group_buy"
    )
    leader: Mapped[User | None] = relationship(back_populates="group_buys")


class Product(Base):
    """可复用于不同团购活动的商品基础信息。"""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    emoji: Mapped[str | None] = mapped_column(String(20), nullable=True)

    group_buy_links: Mapped[list[GroupBuyProduct]] = relationship(
        back_populates="product"
    )


class GroupBuyProduct(Base):
    """商品在某一期团购中的售价与展示配置。"""

    __tablename__ = "group_buy_products"
    __table_args__ = (
        UniqueConstraint(
            "group_buy_id",
            "product_id",
            name="uq_group_buy_products_group_buy_product",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_buy_id: Mapped[int] = mapped_column(
        ForeignKey("group_buys.id"),
        nullable=False,
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"),
        nullable=False,
    )
    sale_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=true(),
        nullable=False,
    )
    last_week_sales: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )

    group_buy: Mapped[GroupBuy] = relationship(back_populates="product_links")
    product: Mapped[Product] = relationship(back_populates="group_buy_links")


class Order(Base):
    """团购订单主表，一条订单可以包含多条商品明细。"""

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint(
            "group_buy_id",
            "follow_no",
            name="uq_orders_group_buy_follow_no",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    group_buy_id: Mapped[int] = mapped_column(
        ForeignKey("group_buys.id"),
        nullable=False,
    )
    group_buy_name: Mapped[str] = mapped_column(String(200), nullable=False)
    follow_no: Mapped[str] = mapped_column(String(20), nullable=False)
    pickup_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pickup_location: Mapped[str | None] = mapped_column(String(100), nullable=True)
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    customer_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="submitted", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=now_in_shanghai,
        nullable=False,
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", name="fk_orders_user_id_users"),
        nullable=True,
        index=True,
    )

    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
    )
    group_buy: Mapped[GroupBuy] = relationship(back_populates="orders")
    user: Mapped[User | None] = relationship(back_populates="orders")


class OrderItem(Base):
    """订单商品明细表，每条明细只属于一个订单。"""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")
