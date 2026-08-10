from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .config import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    echo=False,
)

if "sqlite" in settings.DATABASE_URL:
    # ══ P1-3 性能审计修复：SQLite 并发写锁 ══
    # 默认 journal=delete 模式下，写事务持有整个库的排他锁，多用户并发写
    # 必现 `sqlite3.OperationalError: database is locked` → 500。
    # WAL：读写并发、写写串行化（快很多）；busy_timeout：写锁等待 5s 而非立即报错；
    # synchronous=NORMAL：WAL 下已足够防崩溃损坏（少一次 fsync，写延迟显著下降）。
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ANN001
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
        except Exception:
            # 只读介质/内存库等场景 PRAGMA 失败不阻塞启动
            pass

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def commit_with_retry(db, max_retries=2, base_delay=0.05):
    """P1-3 写操作重试：WAL 下锁冲突概率已大幅降低，但极端并发仍可能
    `database is locked`。提交失败按 50ms → 100ms 退避重试（默认 2 次），
    全部失败则抛出原始异常（由路由层转 500）。
    """
    import time

    for attempt in range(max_retries + 1):
        try:
            db.commit()
            return
        except Exception:
            if attempt >= max_retries:
                raise
            db.rollback()
            time.sleep(base_delay * (2 ** attempt))


def init_db():
    from .models import all_models  # noqa: F401 — 注册所有模型
    Base.metadata.create_all(bind=engine)
