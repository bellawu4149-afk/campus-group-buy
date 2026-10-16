"""Local-only, explicit leader assignment tool. Defaults to dry-run."""

import argparse

from sqlalchemy import select, text

from .database import SessionLocal
from .models import GroupBuy, User


APPLY_CONFIRMATION = "ASSIGN_LEADER"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="受控设置用户团长角色并分配指定团购；默认只预览。"
    )
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--group-buy-id", type=int, required=True, action="append", dest="group_buy_ids")
    parser.add_argument("--apply", action="store_true", help="实际执行；省略时为 dry-run")
    parser.add_argument("--confirm", help=f"实际执行时必须明确填写 {APPLY_CONFIRMATION}")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    group_ids = sorted(set(args.group_buy_ids))
    with SessionLocal() as db:
        user = db.get(User, args.user_id)
        groups = db.scalars(select(GroupBuy).where(GroupBuy.id.in_(group_ids))).all()
        found = {group.id for group in groups}
        missing = sorted(set(group_ids) - found)
        if user is None or missing:
            print(f"检查失败：user_exists={user is not None}, missing_group_buy_ids={missing}")
            return 2
        conflicts = [group.id for group in groups if group.leader_id not in (None, user.id)]
        print(
            f"预览：user_id={user.id}, current_role={user.role}, "
            f"group_buy_ids={group_ids}, conflicting_group_buy_ids={conflicts}"
        )
        print(f"计划角色变更：users.id={user.id}, role: {user.role} -> leader")
        for group in sorted(groups, key=lambda item: item.id):
            current_leader = "NULL" if group.leader_id is None else str(group.leader_id)
            print(
                f"计划归属变更：group_buys.id={group.id}, "
                f"leader_id: {current_leader} -> {user.id}"
            )
        if conflicts:
            print("拒绝执行：存在已归属其他用户的团购。")
            return 2
        if not args.apply:
            print("DRY-RUN：未修改数据库。使用 --apply 并提供显式确认后才会执行。")
            return 0
        if args.confirm != APPLY_CONFIRMATION:
            print(f"拒绝执行：--confirm 必须为 {APPLY_CONFIRMATION}")
            return 2

        db.rollback()
        db.execute(text("BEGIN IMMEDIATE"))
        user = db.get(User, args.user_id)
        locked_groups = db.scalars(select(GroupBuy).where(GroupBuy.id.in_(group_ids))).all()
        if user is None or len(locked_groups) != len(group_ids):
            db.rollback()
            print("执行前复核失败，未修改数据库。")
            return 2
        if any(group.leader_id not in (None, user.id) for group in locked_groups):
            db.rollback()
            print("执行前归属发生变化，未修改数据库。")
            return 2
        user.role = "leader"
        for group in locked_groups:
            group.leader_id = user.id
        db.commit()
        print(f"执行完成：user_id={user.id}, group_buy_ids={group_ids}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
