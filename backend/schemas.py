import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


# 核心评价字段不能为空，并限制长度，避免无效或过长内容写入数据库。
RequiredText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50),
]
FeatureText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]
CustomerName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=30),
]
CustomerPhone = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=30,
        pattern=r"^[0-9+\- ]+$",
    ),
]


class FeedbackCreate(BaseModel):
    """POST /feedback 接收的请求数据。"""

    overall_experience: RequiredText
    convenience: RequiredText
    ranking_helpful: RequiredText
    continue_use: RequiredText
    desired_features: list[FeatureText] = Field(default_factory=list, max_length=20)
    service_satisfaction: int = Field(ge=1, le=5)
    suggestion: str | None = Field(default=None, max_length=1000)


class FeedbackCreated(BaseModel):
    """反馈保存成功后的响应数据。"""

    status: Literal["success"]
    feedback_id: int
    created_at: datetime


class GroupBuyRead(BaseModel):
    """团购活动列表中的公开字段。"""

    id: int
    name: str
    status: str
    created_at: datetime


class GroupBuyProductRead(BaseModel):
    """某一期团购中当前可购买的商品。"""

    product_id: int
    name: str
    description: str | None
    emoji: str | None
    sale_price: Decimal
    display_order: int
    last_week_sales: int


class OrderItemCreate(BaseModel):
    """创建订单时提交的一项商品。"""

    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=9999)


class OrderCreate(BaseModel):
    """POST /orders 接收的请求数据。"""

    model_config = ConfigDict(extra="forbid")

    group_buy_id: int = Field(gt=0)
    customer_name: CustomerName
    customer_phone: CustomerPhone
    pickup_type: Literal["dormitory", "other"]
    pickup_location: str
    items: list[OrderItemCreate] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def normalize_pickup_location(self) -> Self:
        """验证取货位置，并将数据库保存值规范化。"""
        if self.pickup_type == "dormitory":
            if re.fullmatch(r"[0-9]+", self.pickup_location) is None:
                raise ValueError("学生公寓楼栋必须为纯数字")
            building_number = int(self.pickup_location)
            if not 1 <= building_number <= 999:
                raise ValueError("学生公寓楼栋必须在 1～999 之间")
            self.pickup_location = str(building_number)
            return self

        location = self.pickup_location.strip()
        if not 2 <= len(location) <= 100:
            raise ValueError("其他取货位置长度必须为 2～100 个字符")
        self.pickup_location = location
        return self


class OrderCreated(BaseModel):
    """订单创建成功后的响应数据。"""

    status: Literal["success"]
    order_id: int
    order_no: str
    follow_no: str
    customer_name: str
    customer_phone: str
    pickup_type: Literal["dormitory", "other"]
    pickup_location: str
    total_amount: Decimal
    created_at: datetime


class StudentOrderItemRead(BaseModel):
    product_name: str
    unit_price: Decimal
    quantity: int
    subtotal: Decimal


class StudentOrderRead(BaseModel):
    id: int
    order_no: str
    group_buy_id: int
    group_buy_name: str
    follow_no: str
    status: str
    total_amount: Decimal
    created_at: datetime
    customer_name: str
    customer_phone: str | None
    pickup_type: str | None
    pickup_location: str | None
    items: list[StudentOrderItemRead]


class LeaderGroupBuyRead(BaseModel):
    """团长工作台中的团购基本信息。"""

    id: int
    name: str
    status: str
    created_at: datetime


class LeaderSummaryRead(BaseModel):
    order_count: int
    item_count: int
    total_amount: str


class LeaderProductSummaryRead(BaseModel):
    product_name: str
    quantity: int
    amount: str


class LeaderPickupLocationRead(BaseModel):
    location: str
    order_count: int
    item_count: int


class LeaderUnknownPickupRead(BaseModel):
    order_count: int
    item_count: int


class LeaderPickupSummaryRead(BaseModel):
    dormitory: list[LeaderPickupLocationRead]
    other: list[LeaderPickupLocationRead]
    unknown: LeaderUnknownPickupRead


class LeaderDashboardRead(BaseModel):
    group_buy: LeaderGroupBuyRead
    summary: LeaderSummaryRead
    product_summary: list[LeaderProductSummaryRead]
    pickup_summary: LeaderPickupSummaryRead


class LeaderOrderListItemRead(BaseModel):
    id: int
    order_no: str
    follow_no: str
    customer_name: str
    customer_phone: str | None
    pickup_type: str | None
    pickup_location: str | None
    total_amount: str
    status: str
    created_at: datetime
    item_count: int


class LeaderOrderItemRead(BaseModel):
    product_name: str
    unit_price: str
    quantity: int
    subtotal: str


class LeaderOrderDetailRead(BaseModel):
    id: int
    order_no: str
    group_buy_id: int
    group_buy_name: str
    follow_no: str
    customer_name: str
    customer_phone: str | None
    pickup_type: str | None
    pickup_location: str | None
    total_amount: str
    status: str
    created_at: datetime
    items: list[LeaderOrderItemRead]


class LeaderGroupBuyClosed(BaseModel):
    """团长执行截团成功后的响应。"""

    status: Literal["success"]
    group_buy_id: int
    group_buy_status: Literal["closed"]


class LeaderGroupBuyCloneCreate(BaseModel):
    """复制新团时唯一允许由客户端提供的字段。"""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
    ]


class LeaderGroupBuyConfigProductRead(BaseModel):
    group_buy_product_id: int
    product_id: int
    name: str
    sale_price: Decimal
    display_order: int
    is_active: bool
    last_week_sales: int


class LeaderGroupBuyConfigRead(BaseModel):
    group_buy: LeaderGroupBuyRead
    products: list[LeaderGroupBuyConfigProductRead]


class LeaderGroupBuyCloneCreated(BaseModel):
    status: Literal["success"]
    group_buy: LeaderGroupBuyRead
    product_count: int


class LeaderGroupBuyListItemRead(BaseModel):
    id: int
    name: str
    status: str
    created_at: datetime
    order_count: int
    item_count: int
    total_amount: str
    product_count: int


class UserPublicRead(BaseModel):
    """普通业务页面可安全使用的用户字段，不暴露 openid。"""

    id: int
    nickname: str | None
    role: Literal["student", "leader"]
    created_at: datetime


class UserInternalRead(UserPublicRead):
    """仅供后续服务端身份流程使用的内部用户结构。"""

    openid: str | None


class WeChatLoginCreate(BaseModel):
    """微信客户端只允许提交 wx.login 获得的一次性 code。"""

    model_config = ConfigDict(extra="forbid")

    code: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
    ]


class AuthTokenRead(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
    expires_in: int
    user: UserPublicRead
