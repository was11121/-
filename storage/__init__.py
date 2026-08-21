"""集中式用户数据存储层。

职责：把散落在 data/users/<user_id>/*.sqlite3 的每用户数据
统一收进一个集中库（默认 SQLite，可通过 DATABASE_URL 切换 PostgreSQL）。

设计要点：
- 所有业务表都带 user_id 列，按用户分区；
- 通过 SQLAlchemy 方言层屏蔽 SQLite / PostgreSQL 差异；
- 现有 MemoryService / PersonalityService 对外接口不变，仅底层改为本层。
"""

from .db import get_engine, init_db  # noqa: F401

__all__ = ["get_engine", "init_db"]
