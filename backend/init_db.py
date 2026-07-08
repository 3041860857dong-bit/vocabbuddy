"""
初始化数据库：用 root 账号创建库、应用账号并授权，再用 ORM 建表。

运行方式（在 D:\\text\\123 目录下）：
    # 方式一：直接给 root 密码（推荐，命令里带密码）
    set VOCABBUDDY_ROOT_PASSWORD=你的root密码
    python -m backend.init_db

    # 方式二：给完整 root 连接串
    set VOCABBUDDY_ROOT_URL=mysql+pymysql://root:密码@127.0.0.1:3306
    python -m backend.init_db

说明：
- 应用使用的库名/账号：vocabbuddy / vocabbuddy（密码可用 VOCABBUDDY_APP_DB_PASSWORD 覆盖）。
- 建表也可以不跑本脚本——后端启动时 lifespan 会调用 Base.metadata.create_all。
  本脚本主要解决「库和用户不存在」这一步，需要 root 权限。
"""
import os
import sys

# 让 backend 作为包可导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text

DB_NAME = "vocabbuddy"
APP_USER = "vocabbuddy"
APP_PASS = os.getenv("VOCABBUDDY_APP_DB_PASSWORD", "vocabbuddy")

ROOT_URL = os.getenv("VOCABBUDDY_ROOT_URL")
if not ROOT_URL:
    root_pw = os.getenv("VOCABBUDDY_ROOT_PASSWORD")
    if not root_pw:
        raise SystemExit(
            "缺少 root 凭证：请设置 VOCABBUDDY_ROOT_PASSWORD 或 VOCABBUDDY_ROOT_URL"
        )
    ROOT_URL = f"mysql+pymysql://root:{root_pw}@127.0.0.1:3306"


def main():
    root_engine = create_engine(ROOT_URL)
    with root_engine.connect() as conn:
        conn.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )
        # 同时建在 localhost 与 127.0.0.1，覆盖 socket 与 TCP 两种连接方式
        for host in ("localhost", "127.0.0.1", "%"):
            conn.execute(
                text(
                    f"CREATE USER IF NOT EXISTS '{APP_USER}'@'{host}' "
                    f"IDENTIFIED BY '{APP_PASS}'"
                )
            )
            conn.execute(
                text(
                    f"GRANT ALL PRIVILEGES ON `{DB_NAME}`.* TO '{APP_USER}'@'{host}'"
                )
            )
        conn.execute(text("FLUSH PRIVILEGES"))
        print(f"[ok] database `{DB_NAME}` and user `{APP_USER}` are ready")

    # 用应用账号建表
    from backend.db import Base, engine
    from backend import models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(bind=engine)
    print("[ok] tables (users, user_settings) created")


if __name__ == "__main__":
    main()
