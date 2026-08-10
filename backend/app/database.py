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


def _ensure_columns():
    """P0-2 轻量迁移：为已存在的表补齐新增列（SQLite ALTER TABLE ADD COLUMN）。

    Base.metadata.create_all 只建新表、不补旧表缺列；历史 gipfel.db 是旧 schema，
    直接在启动时按模型列清单逐列补齐（新增列均带默认值或可空，SQLite 允许）。
    """
    from .models import all_models  # noqa: F401
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for model in all_models.Base.__subclasses__():
            table = model.__table__.name
            if table not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            for col in model.__table__.columns:
                if col.name in existing_cols:
                    continue
                # 构造 ALTER TABLE ... ADD COLUMN <name> <type> [DEFAULT x]
                col_type = col.type.compile(engine.dialect)
                default = None
                if col.default is not None and col.default.is_scalar:
                    default = col.default.arg
                ddl = f"ALTER TABLE {table} ADD COLUMN {col.name} {col_type}"
                if default is not None:
                    if isinstance(default, str):
                        ddl += f" DEFAULT '{default}'"
                    else:
                        ddl += f" DEFAULT {default}"
                elif not col.nullable:
                    ddl += " DEFAULT ''" if col_type.upper().startswith(("VARCHAR", "TEXT")) else " DEFAULT 0"
                conn.execute(text(ddl))


def init_db():
    from .models import all_models  # noqa: F401 — 注册所有模型
    Base.metadata.create_all(bind=engine)
    _ensure_columns()
