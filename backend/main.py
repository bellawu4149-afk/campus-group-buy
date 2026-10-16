import json
import re
from io import BytesIO
from decimal import Decimal
from urllib.parse import quote
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Response, status
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from sqlalchemy import Integer, cast, func, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from .auth import create_access_token, get_current_user, require_leader
from .config import AUTH_TOKEN_EXPIRE_SECONDS, ConfigurationError
from .database import get_db
from .models import Feedback, GroupBuy, GroupBuyProduct, Order, OrderItem, Product, User
from .schemas import (
    FeedbackCreate,
    FeedbackCreated,
    GroupBuyProductRead,
    GroupBuyRead,
    LeaderDashboardRead,
    LeaderGroupBuyRead,
    LeaderGroupBuyClosed,
    LeaderGroupBuyCloneCreate,
    LeaderGroupBuyCloneCreated,
    LeaderGroupBuyConfigProductRead,
    LeaderGroupBuyConfigRead,
    LeaderGroupBuyListItemRead,
    LeaderOrderDetailRead,
    LeaderOrderItemRead,
    LeaderOrderListItemRead,
    LeaderPickupLocationRead,
    LeaderPickupSummaryRead,
    LeaderProductSummaryRead,
    LeaderSummaryRead,
    LeaderUnknownPickupRead,
    OrderCreate,
    OrderCreated,
    StudentOrderItemRead,
    StudentOrderRead,
    AuthTokenRead,
    UserPublicRead,
    WeChatLoginCreate,
)
from .time_utils import ensure_shanghai_timezone, now_in_shanghai
from .wechat import WeChatExchangeError, exchange_code_for_openid


# 创建 FastAPI 应用。后续新增接口时，可以继续写在这个文件中。
app = FastAPI(
    title="Campus Group Buy API",
    description="校园团购小程序后端 API",
    version="0.1.0",
)

ORDER_CREATE_RETRY_LIMIT = 3


def _money(value: Decimal) -> str:
    """将数据库金额稳定序列化为两位小数字符串。"""
    return format(value.quantize(Decimal("0.01")), ".2f")


def _owned_group_buy_or_404(
    db: Session,
    leader_id: int,
    group_buy_id: int,
) -> GroupBuy:
    """Return only a group owned by this leader, hiding existence otherwise."""
    group_buy = db.scalar(
        select(GroupBuy).where(
            GroupBuy.id == group_buy_id,
            GroupBuy.leader_id == leader_id,
        )
    )
    if group_buy is None:
        raise HTTPException(status_code=404, detail="团购不存在或无权访问")
    return group_buy


@app.get("/health")
def health_check() -> dict[str, str]:
    """健康检查：用于确认后端服务已经正常启动。"""
    return {
        "status": "ok",
        "message": "Campus Group Buy API is running",
    }


def _public_user(user: User) -> UserPublicRead:
    return UserPublicRead(
        id=user.id,
        nickname=user.nickname,
        role=user.role,
        created_at=ensure_shanghai_timezone(user.created_at),
    )


@app.post("/auth/wechat/login", response_model=AuthTokenRead)
def login_with_wechat(
    payload: WeChatLoginCreate,
    db: Session = Depends(get_db),
) -> AuthTokenRead:
    """Exchange an opaque wx.login code server-side and issue our own bearer token."""
    try:
        openid = exchange_code_for_openid(payload.code)
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except WeChatExchangeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    user = db.scalar(select(User).where(User.openid == openid))
    if user is None:
        user = User(openid=openid, role="student")
        db.add(user)
        try:
            db.commit()
            db.refresh(user)
        except IntegrityError:
            # Another first-login request may have inserted the same unique openid.
            db.rollback()
            user = db.scalar(select(User).where(User.openid == openid))
            if user is None:
                raise HTTPException(status_code=503, detail="登录繁忙，请稍后重试")
        except SQLAlchemyError as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail="用户登录失败") from exc

    try:
        token = create_access_token(user)
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return AuthTokenRead(
        access_token=token,
        token_type="bearer",
        expires_in=AUTH_TOKEN_EXPIRE_SECONDS,
        user=_public_user(user),
    )


@app.get("/auth/me", response_model=UserPublicRead)
def read_current_user(current_user: User = Depends(get_current_user)) -> UserPublicRead:
    """Return current database user state; token role is not the authority source."""
    return _public_user(current_user)


@app.get("/group-buys", response_model=list[GroupBuyRead])
def list_group_buys(
    include_closed: bool = False,
    db: Session = Depends(get_db),
) -> list[GroupBuyRead]:
    """按 ID 升序返回开放团购；学生端可请求包含已截团状态用于提示。"""
    statement = select(GroupBuy)
    if not include_closed:
        statement = statement.where(GroupBuy.status == "active")
    group_buys = db.scalars(statement.order_by(GroupBuy.id.asc())).all()
    return [
        GroupBuyRead(
            id=group_buy.id,
            name=group_buy.name,
            status=group_buy.status,
            created_at=ensure_shanghai_timezone(group_buy.created_at),
        )
        for group_buy in group_buys
    ]


@app.get(
    "/group-buys/{group_buy_id}/products",
    response_model=list[GroupBuyProductRead],
)
def list_group_buy_products(
    group_buy_id: int,
    db: Session = Depends(get_db),
) -> list[GroupBuyProductRead]:
    """返回指定团购中当前可购买的商品。"""
    group_buy = db.get(GroupBuy, group_buy_id)
    if group_buy is None:
        raise HTTPException(status_code=404, detail="团购活动不存在")
    if group_buy.status != "active":
        raise HTTPException(status_code=409, detail="团购活动当前不可购买")

    rows = db.execute(
        select(GroupBuyProduct, Product)
        .join(Product, Product.id == GroupBuyProduct.product_id)
        .where(
            GroupBuyProduct.group_buy_id == group_buy.id,
            GroupBuyProduct.is_active.is_(True),
        )
        .order_by(GroupBuyProduct.display_order.asc(), GroupBuyProduct.id.asc())
    ).all()
    return [
        GroupBuyProductRead(
            product_id=product.id,
            name=product.name,
            description=product.description,
            emoji=product.emoji,
            sale_price=link.sale_price,
            display_order=link.display_order,
            last_week_sales=link.last_week_sales,
        )
        for link, product in rows
    ]


@app.post(
    "/feedback",
    response_model=FeedbackCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_feedback(
    payload: FeedbackCreate,
    db: Session = Depends(get_db),
) -> FeedbackCreated:
    """接收用户反馈并保存到 SQLite。"""
    feedback = Feedback(
        overall_experience=payload.overall_experience,
        convenience=payload.convenience,
        ranking_helpful=payload.ranking_helpful,
        continue_use=payload.continue_use,
        # SQLite 原型阶段将多选数组保存为 JSON 文本，读取时可直接还原。
        desired_features=json.dumps(payload.desired_features, ensure_ascii=False),
        service_satisfaction=payload.service_satisfaction,
        suggestion=payload.suggestion,
    )

    try:
        db.add(feedback)
        db.commit()
        db.refresh(feedback)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="反馈保存失败") from exc

    return FeedbackCreated(
        status="success",
        feedback_id=feedback.id,
        created_at=ensure_shanghai_timezone(feedback.created_at),
    )


@app.post(
    "/orders",
    response_model=OrderCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_order(
    payload: OrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OrderCreated:
    """为当前登录用户创建订单，并在同一事务中分配正式跟团号。"""
    # get_current_user 与本接口复用同一个请求 Session，其查询会隐式开启读事务。
    # 保存服务端认证出的 ID 后结束该只读事务，再取得原有 BEGIN IMMEDIATE 写锁。
    authenticated_user_id = current_user.id
    db.rollback()
    for attempt in range(ORDER_CREATE_RETRY_LIMIT):
        try:
            # SQLite BEGIN IMMEDIATE 会在读号前取得写锁，避免并发请求读取同一个最大值。
            db.execute(text("BEGIN IMMEDIATE"))

            group_buy = db.get(GroupBuy, payload.group_buy_id)
            if group_buy is None:
                raise HTTPException(status_code=404, detail="团购活动不存在")
            if group_buy.status != "active":
                raise HTTPException(status_code=409, detail="团购活动当前不可下单")

            item_rows: list[OrderItem] = []
            total_amount = Decimal("0.00")
            for item in payload.items:
                product = db.get(Product, item.product_id)
                if product is None:
                    raise HTTPException(status_code=404, detail="商品不存在")

                product_link = db.scalar(
                    select(GroupBuyProduct).where(
                        GroupBuyProduct.group_buy_id == group_buy.id,
                        GroupBuyProduct.product_id == product.id,
                    )
                )
                if product_link is None:
                    raise HTTPException(status_code=400, detail="商品不属于当前团购")
                if not product_link.is_active:
                    raise HTTPException(status_code=409, detail="商品当前不可购买")

                unit_price = product_link.sale_price
                subtotal = (unit_price * item.quantity).quantize(Decimal("0.01"))
                total_amount += subtotal
                item_rows.append(
                    OrderItem(
                        product_name=product.name,
                        unit_price=unit_price,
                        quantity=item.quantity,
                        subtotal=subtotal,
                    )
                )

            max_follow_number = db.scalar(
                select(func.max(cast(Order.follow_no, Integer))).where(
                    Order.group_buy_id == group_buy.id
                )
            ) or 0
            follow_no = f"{max_follow_number + 1:03d}"
            now = now_in_shanghai()
            order = Order(
                order_no=f"CGB{now:%Y%m%d%H%M%S}{uuid4().hex[:10].upper()}",
                group_buy_id=group_buy.id,
                group_buy_name=group_buy.name,
                follow_no=follow_no,
                pickup_type=payload.pickup_type,
                pickup_location=payload.pickup_location,
                customer_name=payload.customer_name,
                customer_phone=payload.customer_phone,
                total_amount=total_amount,
                status="submitted",
                created_at=now,
                user_id=authenticated_user_id,
                items=item_rows,
            )

            db.add(order)
            db.commit()
            db.refresh(order)
            return OrderCreated(
                status="success",
                order_id=order.id,
                order_no=order.order_no,
                follow_no=order.follow_no,
                customer_name=order.customer_name,
                customer_phone=order.customer_phone,
                pickup_type=order.pickup_type,
                pickup_location=order.pickup_location,
                total_amount=order.total_amount,
                created_at=ensure_shanghai_timezone(order.created_at),
            )
        except HTTPException:
            db.rollback()
            raise
        except (IntegrityError, OperationalError) as exc:
            db.rollback()
            if attempt == ORDER_CREATE_RETRY_LIMIT - 1:
                raise HTTPException(
                    status_code=503,
                    detail="订单提交繁忙，请稍后重试",
                ) from exc
        except SQLAlchemyError as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail="订单创建失败") from exc

    raise HTTPException(status_code=503, detail="订单提交繁忙，请稍后重试")


@app.get("/orders/mine", response_model=list[StudentOrderRead])
def list_my_orders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[StudentOrderRead]:
    """只按服务端认证出的当前用户 ID 返回其订单及商品快照。"""
    orders = db.scalars(
        select(Order)
        .where(Order.user_id == current_user.id)
        .order_by(Order.created_at.desc(), Order.id.desc())
    ).all()
    order_ids = [order.id for order in orders]
    items = (
        db.scalars(
            select(OrderItem)
            .where(OrderItem.order_id.in_(order_ids))
            .order_by(OrderItem.order_id.asc(), OrderItem.id.asc())
        ).all()
        if order_ids
        else []
    )
    items_by_order: dict[int, list[OrderItem]] = {}
    for item in items:
        items_by_order.setdefault(item.order_id, []).append(item)

    return [
        StudentOrderRead(
            id=order.id,
            order_no=order.order_no,
            group_buy_id=order.group_buy_id,
            group_buy_name=order.group_buy_name,
            follow_no=order.follow_no,
            status=order.status,
            total_amount=order.total_amount,
            created_at=ensure_shanghai_timezone(order.created_at),
            customer_name=order.customer_name,
            customer_phone=order.customer_phone,
            pickup_type=order.pickup_type,
            pickup_location=order.pickup_location,
            items=[
                StudentOrderItemRead(
                    product_name=item.product_name,
                    unit_price=item.unit_price,
                    quantity=item.quantity,
                    subtotal=item.subtotal,
                )
                for item in items_by_order.get(order.id, [])
            ],
        )
        for order in orders
    ]


# 当前 leader API 仅用于本地开发和内部试运营。隐藏页面入口不是安全机制；
# 正式部署给其他用户前，必须在服务端增加身份认证和团购权限校验。
@app.get(
    "/leader/group-buys/{group_buy_id}/dashboard",
    response_model=LeaderDashboardRead,
)
def get_leader_dashboard(
    group_buy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_leader),
) -> LeaderDashboardRead:
    """返回指定团购的历史运营概览，不受团购当前状态限制。"""
    group_buy = _owned_group_buy_or_404(db, current_user.id, group_buy_id)

    orders = db.scalars(
        select(Order).where(Order.group_buy_id == group_buy.id)
    ).all()
    order_ids = [order.id for order in orders]
    items = (
        db.scalars(select(OrderItem).where(OrderItem.order_id.in_(order_ids))).all()
        if order_ids
        else []
    )

    item_count_by_order: dict[int, int] = {}
    product_totals: dict[str, tuple[int, Decimal]] = {}
    for item in items:
        item_count_by_order[item.order_id] = (
            item_count_by_order.get(item.order_id, 0) + item.quantity
        )
        quantity, amount = product_totals.get(
            item.product_name,
            (0, Decimal("0.00")),
        )
        product_totals[item.product_name] = (
            quantity + item.quantity,
            amount + item.subtotal,
        )

    pickup_groups: dict[str, dict[str, list[int]]] = {
        "dormitory": {},
        "other": {},
    }
    unknown_order_count = 0
    unknown_item_count = 0
    for order in orders:
        order_item_count = item_count_by_order.get(order.id, 0)
        if (
            order.pickup_type not in pickup_groups
            or order.pickup_location is None
        ):
            unknown_order_count += 1
            unknown_item_count += order_item_count
            continue
        totals = pickup_groups[order.pickup_type].setdefault(
            order.pickup_location,
            [0, 0],
        )
        totals[0] += 1
        totals[1] += order_item_count

    def pickup_rows(kind: str) -> list[LeaderPickupLocationRead]:
        rows = [
            LeaderPickupLocationRead(
                location=location,
                order_count=totals[0],
                item_count=totals[1],
            )
            for location, totals in pickup_groups[kind].items()
        ]
        if kind == "dormitory":
            rows.sort(
                key=lambda row: (
                    0,
                    int(row.location),
                )
                if row.location.isdigit()
                else (1, row.location)
            )
        else:
            rows.sort(key=lambda row: (-row.order_count, row.location))
        return rows

    product_summary = [
        LeaderProductSummaryRead(
            product_name=product_name,
            quantity=quantity,
            amount=_money(amount),
        )
        for product_name, (quantity, amount) in product_totals.items()
    ]
    product_summary.sort(key=lambda row: (-row.quantity, row.product_name))

    return LeaderDashboardRead(
        group_buy=LeaderGroupBuyRead(
            id=group_buy.id,
            name=group_buy.name,
            status=group_buy.status,
            created_at=ensure_shanghai_timezone(group_buy.created_at),
        ),
        summary=LeaderSummaryRead(
            order_count=len(orders),
            item_count=sum(item.quantity for item in items),
            total_amount=_money(
                sum((order.total_amount for order in orders), Decimal("0.00"))
            ),
        ),
        product_summary=product_summary,
        pickup_summary=LeaderPickupSummaryRead(
            dormitory=pickup_rows("dormitory"),
            other=pickup_rows("other"),
            unknown=LeaderUnknownPickupRead(
                order_count=unknown_order_count,
                item_count=unknown_item_count,
            ),
        ),
    )


@app.get(
    "/leader/group-buys/{group_buy_id}/orders",
    response_model=list[LeaderOrderListItemRead],
)
def list_leader_orders(
    group_buy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_leader),
) -> list[LeaderOrderListItemRead]:
    """按下单时间倒序返回指定团购的全部订单。"""
    group_buy = _owned_group_buy_or_404(db, current_user.id, group_buy_id)

    rows = db.execute(
        select(Order, func.coalesce(func.sum(OrderItem.quantity), 0))
        .outerjoin(OrderItem, OrderItem.order_id == Order.id)
        .where(Order.group_buy_id == group_buy.id)
        .group_by(Order.id)
        .order_by(Order.created_at.desc(), Order.id.desc())
    ).all()
    return [
        LeaderOrderListItemRead(
            id=order.id,
            order_no=order.order_no,
            follow_no=order.follow_no,
            customer_name=order.customer_name,
            customer_phone=order.customer_phone,
            pickup_type=order.pickup_type,
            pickup_location=order.pickup_location,
            total_amount=_money(order.total_amount),
            status=order.status,
            created_at=ensure_shanghai_timezone(order.created_at),
            item_count=int(item_count),
        )
        for order, item_count in rows
    ]


@app.get(
    "/leader/orders/{order_id}",
    response_model=LeaderOrderDetailRead,
)
def get_leader_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_leader),
) -> LeaderOrderDetailRead:
    """返回单笔订单及其下单时商品快照。"""
    order = db.scalar(
        select(Order)
        .join(GroupBuy, GroupBuy.id == Order.group_buy_id)
        .where(Order.id == order_id, GroupBuy.leader_id == current_user.id)
    )
    if order is None:
        raise HTTPException(status_code=404, detail="订单不存在或无权访问")
    items = db.scalars(
        select(OrderItem)
        .where(OrderItem.order_id == order.id)
        .order_by(OrderItem.id.asc())
    ).all()
    return LeaderOrderDetailRead(
        id=order.id,
        order_no=order.order_no,
        group_buy_id=order.group_buy_id,
        group_buy_name=order.group_buy_name,
        follow_no=order.follow_no,
        customer_name=order.customer_name,
        customer_phone=order.customer_phone,
        pickup_type=order.pickup_type,
        pickup_location=order.pickup_location,
        total_amount=_money(order.total_amount),
        status=order.status,
        created_at=ensure_shanghai_timezone(order.created_at),
        items=[
            LeaderOrderItemRead(
                product_name=item.product_name,
                unit_price=_money(item.unit_price),
                quantity=item.quantity,
                subtotal=_money(item.subtotal),
            )
            for item in items
        ],
    )


@app.post(
    "/leader/group-buys/{group_buy_id}/close",
    response_model=LeaderGroupBuyClosed,
)
def close_leader_group_buy(
    group_buy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_leader),
) -> LeaderGroupBuyClosed:
    """以原子状态更新将 active 团购截为 closed。"""
    leader_id = current_user.id
    try:
        # 结束认证查询的隐式读事务，取得写锁后在同一事务内重新验证归属。
        db.rollback()
        db.execute(text("BEGIN IMMEDIATE"))
        group_buy = _owned_group_buy_or_404(db, leader_id, group_buy_id)
        result = db.execute(
            update(GroupBuy)
            .where(
                GroupBuy.id == group_buy_id,
                GroupBuy.leader_id == leader_id,
                GroupBuy.status == "active",
            )
            .values(status="closed")
        )
        if result.rowcount == 1:
            db.commit()
            return LeaderGroupBuyClosed(
                status="success",
                group_buy_id=group_buy_id,
                group_buy_status="closed",
            )

        db.rollback()
        if group_buy.status == "closed":
            raise HTTPException(status_code=409, detail="团购已截团")
        raise HTTPException(status_code=409, detail="团购活动当前状态不可截团")
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="截团失败") from exc


def _display_pickup(pickup_type: str | None, location: str | None) -> str:
    if pickup_type is None or location is None:
        return "未记录"
    return f"学生公寓{location}栋" if pickup_type == "dormitory" else location


def _style_excel_table(sheet, header_row: int, widths: list[float]) -> None:
    for cell in sheet[header_row]:
        cell.font = Font(bold=True)
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = f"A{header_row + 1}"


def _build_group_buy_workbook(
    group_buy: GroupBuy,
    dashboard: LeaderDashboardRead,
    orders: list[Order],
    items_by_order: dict[int, list[OrderItem]],
    exported_at,
) -> bytes:
    workbook = Workbook()
    product_sheet = workbook.active
    product_sheet.title = "商品汇总"
    product_sheet.append(["团购名称", group_buy.name])
    product_sheet.append(["团购状态", "已截团"])
    product_sheet.append(["导出时间", exported_at.strftime("%Y-%m-%d %H:%M:%S")])
    product_sheet.append(["订单总数", dashboard.summary.order_count, "商品总件数", dashboard.summary.item_count, "成交总额", Decimal(dashboard.summary.total_amount)])
    product_sheet["F4"].number_format = "0.00"
    product_sheet.append([])
    product_sheet.append(["商品名称", "总数量", "成交金额"])
    for row in dashboard.product_summary:
        product_sheet.append([row.product_name, row.quantity, Decimal(row.amount)])
        product_sheet.cell(product_sheet.max_row, 3).number_format = "0.00"
    product_sheet.append(["合计", dashboard.summary.item_count, Decimal(dashboard.summary.total_amount)])
    product_sheet.cell(product_sheet.max_row, 3).number_format = "0.00"
    product_sheet.cell(product_sheet.max_row, 1).font = Font(bold=True)
    _style_excel_table(product_sheet, 6, [32, 14, 16, 14, 14, 16])

    detail_sheet = workbook.create_sheet("订单明细")
    detail_sheet.append([
        "跟团号", "联系人", "联系电话", "取货位置", "商品名称", "单价",
        "数量", "商品小计", "订单总金额", "订单状态", "下单时间", "订单号",
    ])
    for order in orders:
        for item in items_by_order.get(order.id, []):
            detail_sheet.append([
                order.follow_no,
                order.customer_name,
                order.customer_phone or "未记录",
                _display_pickup(order.pickup_type, order.pickup_location),
                item.product_name,
                item.unit_price,
                item.quantity,
                item.subtotal,
                order.total_amount,
                "已提交" if order.status == "submitted" else order.status,
                ensure_shanghai_timezone(order.created_at).strftime("%Y-%m-%d %H:%M:%S"),
                order.order_no,
            ])
            for column in (6, 8, 9):
                detail_sheet.cell(detail_sheet.max_row, column).number_format = "0.00"
    _style_excel_table(
        detail_sheet,
        1,
        [12, 14, 18, 20, 32, 12, 10, 14, 16, 12, 22, 34],
    )

    pickup_sheet = workbook.create_sheet("配送汇总")
    pickup_sheet.append(["取货类型", "取货位置", "订单数", "商品件数"])
    for row in dashboard.pickup_summary.dormitory:
        pickup_sheet.append(["学生公寓", f"{row.location}栋", row.order_count, row.item_count])
    for row in dashboard.pickup_summary.other:
        pickup_sheet.append(["其他", row.location, row.order_count, row.item_count])
    if dashboard.pickup_summary.unknown.order_count:
        pickup_sheet.append([
            "历史未记录",
            "未记录",
            dashboard.pickup_summary.unknown.order_count,
            dashboard.pickup_summary.unknown.item_count,
        ])
    _style_excel_table(pickup_sheet, 1, [18, 24, 12, 14])

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


@app.get("/leader/group-buys/{group_buy_id}/export.xlsx")
def export_leader_group_buy_excel(
    group_buy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_leader),
) -> Response:
    """在截团后以内存工作簿导出最终商家备货表。"""
    group_buy = _owned_group_buy_or_404(db, current_user.id, group_buy_id)
    if group_buy.status != "closed":
        raise HTTPException(status_code=409, detail="请先截团后再导出最终备货表")

    dashboard = get_leader_dashboard(group_buy_id, db, current_user)
    orders = db.scalars(
        select(Order)
        .where(Order.group_buy_id == group_buy_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
    ).all()
    order_ids = [order.id for order in orders]
    items = (
        db.scalars(
            select(OrderItem)
            .where(OrderItem.order_id.in_(order_ids))
            .order_by(OrderItem.id.asc())
        ).all()
        if order_ids
        else []
    )
    items_by_order: dict[int, list[OrderItem]] = {}
    for item in items:
        items_by_order.setdefault(item.order_id, []).append(item)

    exported_at = now_in_shanghai()
    content = _build_group_buy_workbook(
        group_buy,
        dashboard,
        list(orders),
        items_by_order,
        exported_at,
    )
    safe_name = re.sub(r'[\\/:*?"<>|]+', "_", group_buy.name).strip(" ._")
    safe_name = (safe_name or f"group_buy_{group_buy.id}")[:80]
    display_name = f"{safe_name}_备货表_{exported_at:%Y%m%d_%H%M%S}.xlsx"
    fallback_name = f"group_buy_{group_buy.id}_stock_{exported_at:%Y%m%d_%H%M%S}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{fallback_name}"; '
                f"filename*=UTF-8''{quote(display_name)}"
            )
        },
    )


@app.get(
    "/leader/group-buys/{group_buy_id}/config",
    response_model=LeaderGroupBuyConfigRead,
)
def get_leader_group_buy_config(
    group_buy_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_leader),
) -> LeaderGroupBuyConfigRead:
    """返回 active 或 closed 来源团可复制的只读商品配置。"""
    group_buy = _owned_group_buy_or_404(db, current_user.id, group_buy_id)
    rows = db.execute(
        select(GroupBuyProduct, Product)
        .join(Product, Product.id == GroupBuyProduct.product_id)
        .where(GroupBuyProduct.group_buy_id == group_buy_id)
        .order_by(GroupBuyProduct.display_order.asc(), GroupBuyProduct.id.asc())
    ).all()
    return LeaderGroupBuyConfigRead(
        group_buy=LeaderGroupBuyRead(
            id=group_buy.id,
            name=group_buy.name,
            status=group_buy.status,
            created_at=ensure_shanghai_timezone(group_buy.created_at),
        ),
        products=[
            LeaderGroupBuyConfigProductRead(
                group_buy_product_id=link.id,
                product_id=product.id,
                name=product.name,
                sale_price=link.sale_price,
                display_order=link.display_order,
                is_active=link.is_active,
                last_week_sales=link.last_week_sales,
            )
            for link, product in rows
        ],
    )


@app.post(
    "/leader/group-buys/{source_group_buy_id}/clone",
    response_model=LeaderGroupBuyCloneCreated,
    status_code=status.HTTP_201_CREATED,
)
def clone_leader_group_buy(
    source_group_buy_id: int,
    payload: LeaderGroupBuyCloneCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_leader),
) -> LeaderGroupBuyCloneCreated:
    """在单一事务中创建 active 新团并复制源团当前商品配置。"""
    leader_id = current_user.id
    try:
        # 在写锁事务内重新验证来源归属，避免检查后归属发生变化。
        db.rollback()
        db.execute(text("BEGIN IMMEDIATE"))
        source = _owned_group_buy_or_404(db, leader_id, source_group_buy_id)
        source_links = db.scalars(
            select(GroupBuyProduct)
            .where(GroupBuyProduct.group_buy_id == source.id)
            .order_by(GroupBuyProduct.display_order.asc(), GroupBuyProduct.id.asc())
        ).all()
        new_group_buy = GroupBuy(
            name=payload.name,
            status="active",
            created_at=now_in_shanghai(),
            leader_id=leader_id,
        )
        db.add(new_group_buy)
        db.flush()
        db.add_all([
            GroupBuyProduct(
                group_buy_id=new_group_buy.id,
                product_id=source_link.product_id,
                sale_price=source_link.sale_price,
                display_order=source_link.display_order,
                is_active=source_link.is_active,
                last_week_sales=source_link.last_week_sales,
            )
            for source_link in source_links
        ])
        db.commit()
        db.refresh(new_group_buy)
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="复制团购失败") from exc

    return LeaderGroupBuyCloneCreated(
        status="success",
        group_buy=LeaderGroupBuyRead(
            id=new_group_buy.id,
            name=new_group_buy.name,
            status=new_group_buy.status,
            created_at=ensure_shanghai_timezone(new_group_buy.created_at),
        ),
        product_count=len(source_links),
    )


@app.get(
    "/leader/group-buys",
    response_model=list[LeaderGroupBuyListItemRead],
)
def list_leader_group_buys(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_leader),
) -> list[LeaderGroupBuyListItemRead]:
    """一次聚合返回当前团长拥有的团购。"""
    order_totals = (
        select(
            Order.group_buy_id.label("group_buy_id"),
            func.count(Order.id).label("order_count"),
            func.coalesce(func.sum(Order.total_amount), 0).label("total_amount"),
        )
        .group_by(Order.group_buy_id)
        .subquery()
    )
    item_totals = (
        select(
            Order.group_buy_id.label("group_buy_id"),
            func.coalesce(func.sum(OrderItem.quantity), 0).label("item_count"),
        )
        .join(OrderItem, OrderItem.order_id == Order.id)
        .group_by(Order.group_buy_id)
        .subquery()
    )
    product_totals = (
        select(
            GroupBuyProduct.group_buy_id.label("group_buy_id"),
            func.count(GroupBuyProduct.id).label("product_count"),
        )
        .group_by(GroupBuyProduct.group_buy_id)
        .subquery()
    )
    rows = db.execute(
        select(
            GroupBuy,
            func.coalesce(order_totals.c.order_count, 0),
            func.coalesce(item_totals.c.item_count, 0),
            func.coalesce(order_totals.c.total_amount, 0),
            func.coalesce(product_totals.c.product_count, 0),
        )
        .outerjoin(order_totals, order_totals.c.group_buy_id == GroupBuy.id)
        .outerjoin(item_totals, item_totals.c.group_buy_id == GroupBuy.id)
        .outerjoin(product_totals, product_totals.c.group_buy_id == GroupBuy.id)
        .where(GroupBuy.leader_id == current_user.id)
        .order_by(GroupBuy.created_at.desc(), GroupBuy.id.desc())
    ).all()
    return [
        LeaderGroupBuyListItemRead(
            id=group_buy.id,
            name=group_buy.name,
            status=group_buy.status,
            created_at=ensure_shanghai_timezone(group_buy.created_at),
            order_count=int(order_count),
            item_count=int(item_count),
            total_amount=_money(Decimal(total_amount)),
            product_count=int(product_count),
        )
        for group_buy, order_count, item_count, total_amount, product_count in rows
    ]
