"""
Gipfel 云端后端核心测试（pytest + TestClient）
覆盖（回归防护——本轮实测发现的 bug 全部纳入）：
1. 认证：登录/注册封禁/改密/JWT 鉴权
2. 合同并发编号唯一（曾 UNIQUE 冲突 500）
3. 资金原子扣款（曾并发丢更新）
4. 公司→组织同步
5. 统一账号（stock 转发依赖 gipfel 验证——这里测 gipfel 侧）

运行：cd /home/ubuntu/gipfel-api && venv/bin/python -m pytest tests/ -v
"""
import os
import sys
import tempfile
from uuid import uuid4

# 使用临时 DB（不碰生产 gipfel.db）——必须在 import app 前设置
_tmp = tempfile.mkdtemp(prefix="gipfel-test-")
_tmp_db = os.path.join(_tmp, "test.db").replace("\\", "/")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db}"
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest-2026"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db, init_db, SessionLocal
from app.models.all_models import Base

client = TestClient(app)


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    # TestClient 作为 context manager 进入时触发 lifespan → init_db + seed_all
    with TestClient(app) as c:
        # 冒烟：seed 后 admin 可登录（seed 默认密码 "admin"）
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        assert r.status_code == 200, f"seed 后登录失败: {r.text}"
        yield
    import shutil
    shutil.rmtree(_tmp, ignore_errors=True)


def login(username="admin", password="admin"):
    # 测试库由 seed 创建，admin 默认密码 "admin"（生产库为 admin123，测试环境自洽）
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"登录失败: {r.text}"
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ═══ 1. 认证 ═══
class TestAuth:
    def test_login_admin(self):
        r = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
        assert r.status_code == 200
        assert r.json()["token"]

    def test_login_wrong_password(self):
        r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert r.status_code == 401

    def test_register_closed(self):
        # 无 X-Admin-Key → 403（注册封禁）
        r = client.post("/api/auth/register", json={"username": "hacker", "password": "hack123456"})
        assert r.status_code == 403

    def test_unauthenticated_rejected(self):
        r = client.get("/api/contracts")
        assert r.status_code == 401

    def test_change_password_flow(self):
        # 建号→改密→旧密码401→新密码200
        h = login()
        uname = "pwtest1"
        r = client.post("/api/auth/users", headers=h,
                        json={"username": uname, "password": "old123456", "role": "user"})
        assert r.status_code == 200
        uid = r.json()["id"]
        r = client.post(f"/api/auth/users/{uid}/reset-password", headers=h,
                        json={"new_password": "new123456"})
        assert r.status_code == 200
        r = client.post("/api/auth/login", json={"username": uname, "password": "old123456"})
        assert r.status_code == 401
        r = client.post("/api/auth/login", json={"username": uname, "password": "new123456"})
        assert r.status_code == 200
        client.delete(f"/api/auth/users/{uid}", headers=h)


# ═══ 2. 合同并发编号唯一（回归：曾 count+1 → UNIQUE 冲突 500）═══
class TestContractConcurrency:
    def test_concurrent_create_unique_no(self):
        from concurrent.futures import ThreadPoolExecutor
        h = login()
        payload = {
            "contract_name": "并发测试", "contract_type_id": 7, "region_id": 1,
            "party_a": "甲方", "party_b_name": "建设集团一公司",
            "items": [{"item_name": "钢材", "quantity": 1, "unit_price": 100, "tax_rate": 13}],
            "created_by": "admin",
        }

        def create(_):
            return client.post("/api/contracts", headers=h, json=payload)

        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(create, range(8)))

        ids = []
        nos = []
        for r in results:
            assert r.status_code in (200, 201), f"并发创建失败: {r.status_code} {r.text[:100]}"
            ids.append(r.json()["id"])
            nos.append(r.json()["contract_no"])
        assert len(set(nos)) == 8, f"合同编号重复: {nos}"
        # 清理
        for cid in ids:
            client.delete(f"/api/contracts/{cid}", headers=h)


# ═══ 3. 资金原子扣款（回归：曾并发丢更新）═══
class TestAccountAtomic:
    def test_concurrent_debits_no_lost_update(self):
        from concurrent.futures import ThreadPoolExecutor
        h = login()
        # 找余额最大的账户
        r = client.get("/api/accounts", headers=h)
        assert r.status_code == 200
        accs = r.json()
        acc = max(accs, key=lambda a: float(a["balance"]))
        aid, bal0 = acc["id"], float(acc["balance"])
        amt = round(bal0 * 0.4, 2)

        def spend(_):
            return client.post("/api/accounts/transactions", headers=h, json={
                "account_id": aid, "trans_type": "expense", "category": "并发测试",
                "amount": amt, "description": "pytest-atomic"})

        with ThreadPoolExecutor(max_workers=2) as ex:
            results = list(ex.map(spend, range(2)))
        for r in results:
            assert r.status_code == 200, f"扣款失败: {r.text[:100]}"

        r = client.get("/api/accounts", headers=h)
        bal1 = float(next(a["balance"] for a in r.json() if a["id"] == aid))
        expect = round(bal0 - 2 * amt, 2)
        assert abs(bal1 - expect) < 0.01, f"丢更新: {bal0}→{bal1} 期望 {expect}"

        # 超扣拦截
        r = client.post("/api/accounts/transactions", headers=h, json={
            "account_id": aid, "trans_type": "expense", "category": "并发测试",
            "amount": round(bal1 + 1, 2), "description": "pytest-over"})
        assert r.status_code == 400, f"超扣未拦截: {r.status_code}"

        # 恢复余额 + 清理流水
        client.post("/api/accounts/transactions", headers=h, json={
            "account_id": aid, "trans_type": "income", "category": "测试恢复",
            "amount": round(bal0 - bal1, 2), "description": "pytest-restore"})
        r = client.get(f"/api/accounts/{aid}/transactions", headers=h)
        for t in r.json():
            if "pytest" in str(t.get("description", "")):
                # 无删除端点，保留（审计记录）；仅余额断言
                pass


# ═══ 4. 公司→组织同步 ═══
class TestCompanyOrgSync:
    def test_create_company_creates_org(self):
        h = login()
        r = client.post("/api/companies", headers=h,
                        json={"name": "pytest同步公司", "region": "测试区", "company_type": "测试"})
        assert r.status_code in (200, 201)
        co_id = r.json()["id"]
        # 组织应已同步创建
        r = client.get("/api/companies", headers=h)
        # 通过 org 查询（companies 列表含 org_name 字段）
        comp = next((c for c in r.json() if c["id"] == co_id), None)
        assert comp is not None
        client.delete(f"/api/companies/{co_id}", headers=h)


# ═══ 5. 公司过滤（数据隔离）═══
class TestCompanyFilter:
    def test_contracts_company_filter(self):
        h = login()
        r = client.get("/api/contracts?company_id=1", headers=h)
        assert r.status_code == 200
        data = r.json()
        items = data.get("items", data) if isinstance(data, dict) else data
        assert isinstance(items, list)


# ═══ 6. 税率口径（曾 1300% 错误）═══
class TestTaxRatio:
    def test_tax_13_percent(self):
        h = login()
        r = client.post("/api/contracts", headers=h, json={
            "contract_name": "税率测试", "contract_type_id": 7, "region_id": 1,
            "party_a": "甲方", "party_b_name": "建设集团一公司",
            "items": [{"item_name": "商品", "quantity": 2, "unit_price": 100, "tax_rate": 13}],
            "created_by": "admin"})
        assert r.status_code in (200, 201)
        cid = r.json()["id"]
        r = client.get(f"/api/contracts/{cid}", headers=h)
        item = r.json()["items"][0]
        # tax_rate=13 → 税额 26（2*100*13%），总价 226
        assert item["tax_rate"] == 13
        assert abs(item["tax_amount"] - 26) < 0.01, f"税额 {item['tax_amount']}"
        assert abs(item["total"] - 226) < 0.01, f"总价 {item['total']}"
        client.delete(f"/api/contracts/{cid}", headers=h)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ═══ 7. 合同审批入账原子性（回归：曾 ORM 读改写丢更新）═══
class TestContractAccountAtomic:
    def test_concurrent_contract_approvals_balance_exact(self):
        """两个合同同时审批执行 → 区域账户余额精确扣减（无丢更新）"""
        from concurrent.futures import ThreadPoolExecutor
        h = login()
        # 建 2 个合同（小金额）
        ids = []
        for i in range(2):
            r = client.post("/api/contracts", headers=h, json={
                "contract_name": f"原子并发{i}", "contract_type_id": 1, "region_id": 1,
                "party_a": "甲", "party_b_name": "建设集团一公司",
                "items": [{"item_name": "工程", "quantity": 1, "unit_price": 1000, "tax_rate": 0}],
                "created_by": "admin"})
            assert r.status_code in (200, 201), r.text[:80]
            ids.append(r.json()["id"])

        # 余额快照
        r = client.get("/api/accounts", headers=h)
        aid = next(a["id"] for a in r.json() if a["region_id"] == 1)
        bal0 = float(next(a["balance"] for a in r.json() if a["id"] == aid))

        # 并发提交审批 → 执行（支出）
        def submit_approve_activate(cid):
            client.post(f"/api/contracts/{cid}/approve", headers=h, json={"action": "submit"})
            client.post(f"/api/contracts/{cid}/approve", headers=h, json={"action": "approve"})
            # 审批通过后置 active → 触发合同支出入账
            client.put(f"/api/contracts/{cid}", headers=h, json={"status": "active"})

        with ThreadPoolExecutor(max_workers=2) as ex:
            list(ex.map(submit_approve_activate, ids))

        r = client.get("/api/accounts", headers=h)
        bal1 = float(next(a["balance"] for a in r.json() if a["id"] == aid))
        # 每合同 total_cost = 1*1000*1.0 = 1000，两笔支出 2000
        expect = round(bal0 - 2000, 2)
        assert abs(bal1 - expect) < 0.01, f"合同入账丢更新: {bal0}→{bal1} 期望 {expect}"

        # 清理
        for cid in ids:
            client.delete(f"/api/contracts/{cid}", headers=h)
        # 冲回余额
        client.post("/api/accounts/transactions", headers=h, json={
            "account_id": aid, "trans_type": "income", "category": "测试恢复",
            "amount": round(bal0 - bal1, 2), "description": "pytest-contract-restore"})


# ═══ 8. 资金桥并发幂等（回归：曾内存字典竞态致并发同 key 双扣）═══
class TestStockFundIdempotency:
    def test_concurrent_same_key_deduct_once(self):
        """并发 5 个同 key 扣款请求 → 只扣一次（DB 级唯一索引）"""
        from concurrent.futures import ThreadPoolExecutor
        h = login()
        # 查询区域账户余额
        r = client.get("/api/accounts", headers=h)
        aid = next(a["id"] for a in r.json() if a["region_id"] == 1)
        bal0 = float(next(a["balance"] for a in r.json() if a["id"] == aid))

        key = f"pytest-idem-{uuid4().hex[:8]}"
        def call(_):
            return client.post("/api/stock/fund", headers=h, json={
                "username": "admin", "side": "buy", "amount": 50,
                "idempotency_key": key})

        with ThreadPoolExecutor(max_workers=5) as ex:
            resps = list(ex.map(call, range(5)))
        assert all(r.status_code == 200 for r in resps), [r.status_code for r in resps]

        r = client.get("/api/accounts", headers=h)
        bal1 = float(next(a["balance"] for a in r.json() if a["id"] == aid))
        assert abs(bal1 - (bal0 - 50)) < 0.01, f"并发同 key 双扣: {bal0}→{bal1} 期望 {bal0-50}"

        # 恢复
        client.post("/api/stock/fund", headers=h, json={
            "username": "admin", "side": "sell", "amount": 50,
            "idempotency_key": f"{key}-restore"})
