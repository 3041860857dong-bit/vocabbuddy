"""
数据库引擎与会话管理（SQLAlchemy 2.0）。

- 连接串来自 config.DB_URL（MySQL / SQLite 皆可用）。
- pool_pre_ping=True：每次取连接前探测，自动剔除已断开的连接，提升稳定性。
- SQLite 需要 check_same_thread=False 才能在 FastAPI 的线程池中复用连接。
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import DB_URL

_connect_args = {}
if DB_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    DB_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
)

Base = declarative_base()


def get_db():
    """FastAPI 依赖：每个请求一个会话，结束后自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
