"""FastAPI 主入口"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import init_db
from .routes import (
    auth, regions, companies, contracts, dashboard, formula, reports, infra,
    accounts, excel, announcements, audit, notifications, backup,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from .database import SessionLocal
    from .services.seed import seed_all
    db = SessionLocal()
    try:
        seed_all(db)
    finally:
        db.close()
    yield

app = FastAPI(
    title="Gipfel 模拟系统 API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router, prefix="/api/auth", tags=["认证"])
app.include_router(regions.router, prefix="/api/regions", tags=["区域"])
app.include_router(companies.router, prefix="/api/companies", tags=["公司"])
app.include_router(contracts.router, prefix="/api/contracts", tags=["合同"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["仪表盘"])
app.include_router(formula.router, prefix="/api/formula", tags=["模拟计算"])
app.include_router(reports.router, prefix="/api/reports", tags=["报表"])
app.include_router(infra.router, prefix="/api/infra", tags=["基建"])
app.include_router(accounts.router, prefix="/api/accounts", tags=["财务"])
app.include_router(excel.router, prefix="/api/excel", tags=["Excel"])
app.include_router(announcements.router, prefix="/api/announcements", tags=["公告"])
app.include_router(audit.router, prefix="/api/audit", tags=["审计"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["通知"])
app.include_router(backup.router, prefix="/api/backup", tags=["备份"])
from .routes.stock_fund import router as stock_fund_router
app.include_router(stock_fund_router, tags=["股票资金桥"])


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "2.0.0"}
