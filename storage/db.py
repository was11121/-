"""集中库统一入口：解析 DATABASE_URL，管理 Engine / Session / 建表。

默认 `DATABASE_URL` 未设置时使用 SQLite: <data>/users.db；
生产可设置如 `postgresql+psycopg2://user:pass@host:5432/myagent`。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base

_engines: dict[str, Engine] = {}
_session_factories: dict[str, sessionmaker] = {}


def _default_url(data_dir: str | Path | None = None) -> str:
    root = Path(data_dir) if data_dir else Path(
        os.getenv("MYAGENT_DATA_DIR", Path(__file__).resolve().parents[1] / "data")
    )
    root.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(root / 'users.db').as_posix()}"


def get_database_url(data_dir: str | Path | None = None) -> str:
    """返回实际生效的 DATABASE_URL（环境变量优先）。"""
    return os.getenv("DATABASE_URL") or _default_url(data_dir)


def get_engine(data_dir: str | Path | None = None) -> Engine:
    """获取（并复用）数据库引擎。datasource 由 DATABASE_URL 决定。

    每个不同的 URL 建一个引擎（测试会为每个临时 data_dir 建独立 SQLite 库），
    生产环境 DATABASE_URL 全局唯一，只会有一个引擎。
    """
    url = get_database_url(data_dir)
    if url in _engines:
        return _engines[url]

    kwargs: dict[str, Any] = {}
    if url.startswith("sqlite"):
        # 单个 SQLite 文件即可，方便单文件备份；
        # 内存库用于测试。
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            # 文件型 SQLite：NullPool 用完即关，避免连接池句柄常驻锁住 .db
            # 文件（否则 Windows 上无法删除/备份 users.db；本地单进程无性能损失）
            from sqlalchemy.pool import NullPool

            kwargs["poolclass"] = NullPool
            kwargs["connect_args"] = {"check_same_thread": False}

    engine = create_engine(url, future=True, pool_pre_ping=True, **kwargs)

    if url.startswith("sqlite"):
        # 默认 rollback journal 模式：连接关闭即释放文件句柄，
        # 方便删除/备份 users.db。（WAL 的 -wal/-shm 在 Windows 上会残留锁文件）
        @event.listens_for(engine, "connect")
        def _set_pragma(dbapi_connection, connection_record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _engines[url] = engine
    return engine


def get_session(data_dir: str | Path | None = None) -> Session:
    url = get_database_url(data_dir)
    factory = _session_factories.get(url)
    if factory is None:
        factory = sessionmaker(bind=get_engine(data_dir), future=True, expire_on_commit=False)
        _session_factories[url] = factory
    return factory()


def init_db(data_dir: str | Path | None = None) -> None:
    """创建所有表（幂等）。"""
    Base.metadata.create_all(get_engine(data_dir))


def reset_engine() -> None:
    """测试用：重置全部单例，便于换数据库。"""
    for engine in _engines.values():
        engine.dispose()
    _engines.clear()
    _session_factories.clear()
