"""交付前验收审计：云端 ROUTE_MAP 逐端点探测（对 gipfel-saas backend，临时库 acceptance-audit.db）"""
import json, urllib.request, urllib.error

BASE = "http://127.0.0.1:8791"

def req(method, path, body=None, token=None, expect_json=True):
    headers = {}
    if token: headers["Authorization"] = f"Bearer {token}"
    if body is not None: headers["Content-Type"] = "application/json"
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        resp = urllib.request.urlopen(r, timeout=10)
        raw = resp.read()
        note = ""
        try:
            j = json.loads(raw)
            if isinstance(j, dict):
                keys = ",".join(list(j.keys())[:8])
                note = f"keys[{keys}]"
            elif isinstance(j, list):
                note = f"list[{len(j)}]"
                if j: note += " keys[" + ",".join(list(j[0].keys())[:10]) + "]"
        except Exception:
            note = raw[:60].decode(errors="replace")
        return resp.status, note, raw
    except urllib.error.HTTPError as e:
        raw = e.read()
        note = raw[:120].decode(errors="replace").replace("\n", " ")
        return e.code, note, raw
    except Exception as e:
        return "ERR", str(e)[:120], b""

# 1. 登录
st, note, _ = req("POST", "/api/auth/login", {"username": "admin", "password": "admin"})
print(f"[login] {st} {note}")
token = json.loads(_)["token"] if st == 200 else None

# 2. 建一个区域/公司/合同供查询
if token:
    st, _, _ = req("POST", "/api/regions", {"name": "验收区"}, token)
    st, _, _ = req("POST", "/api/companies", {"name": "验收公司"}, token)
    st, raw, _ = req("POST", "/api/contracts", {
        "contract_name": "验收合同", "contract_type_id": None, "region_id": 1,
        "party_a": "甲", "party_b_name": "验收公司", "status": "draft",
        "items": [{"item_name": "商品", "quantity": 2, "unit_price": 100, "tax_rate": 13}]
    }, token)
    print(f"[seed contract:create] {st} {raw[:150]}")

PROBES = [
    ("GET",  "/api/health", None, "system:health"),
    ("GET",  "/api/regions", None, "region:list"),
    ("GET",  "/api/regions/1", None, "region:get"),
    ("POST", "/api/regions", {"name": "探测区2"}, "region:create"),
    ("PUT",  "/api/regions/1", {"name": "验收区改"}, "region:update"),
    ("DELETE","/api/regions/99999", None, "region:delete"),
    ("GET",  "/api/companies", None, "company:list"),
    ("POST", "/api/companies", {"name": "探测公司2"}, "company:create"),
    ("PUT",  "/api/companies/1", {"name": "验收公司改"}, "company:update"),
    ("GET",  "/api/contracts?limit=200", None, "contract:list(limit=200 分页形态)"),
    ("GET",  "/api/contracts/1", None, "contract:get(缺items?)"),
    ("PUT",  "/api/contracts/1", {"contract_name": "改名"}, "contract:update ← ROUTE_MAP PUT"),
    ("POST", "/api/contracts/1/approve", {"action": "submit"}, "contract:approve ← ROUTE_MAP"),
    ("POST", "/api/contracts/batch-approve", {"ids": [1], "action": "submit"}, "contract:batch-approve ← ROUTE_MAP"),
    ("GET",  "/api/contracts/1/summarize", None, "contract:summarize ← ROUTE_MAP"),
    ("GET",  "/api/contracts/summarize/1", None, "cloud实际summarize路径"),
    ("GET",  "/api/contracts/1/versions", None, "contract:list-versions ← ROUTE_MAP"),
    ("GET",  "/api/contract-types", None, "contract-type:list ← ROUTE_MAP"),
    ("GET",  "/api/infra-types", None, "infra-type:list ← ROUTE_MAP(实际在/api/infra/types)"),
    ("GET",  "/api/infra/types", None, "cloud实际 infra types"),
    ("GET",  "/api/dashboard/summary", None, "dashboard:summary ← ROUTE_MAP(approval_status崩溃?)"),
    ("GET",  "/api/dashboard/system-stats", None, "dashboard:system-stats ← ROUTE_MAP"),
    ("POST", "/api/formula/calculate", {"region_id": 1, "population": 1000, "talent_population": 100, "carbon_emissions": 50}, "formula:calculate"),
    ("GET",  "/api/formula/logs?region_id=1", None, "formula:log-list ← ROUTE_MAP(实际/logs/{id})"),
    ("GET",  "/api/formula/logs/1", None, "cloud实际 formula logs"),
    ("GET",  "/api/infra-calc?region_id=1", None, "infra-calc:load ← ROUTE_MAP(实际/api/infra/calculate)"),
    ("GET",  "/api/infra/calculate?region_id=1", None, "cloud实际 infra-calc"),
    ("GET",  "/api/accounts", None, "account:list"),
    ("GET",  "/api/accounts/summary", None, "account:summary ← ROUTE_MAP(实际/summary/all)"),
    ("GET",  "/api/accounts/summary/all", None, "cloud实际 account summary"),
    ("POST", "/api/accounts", {"account_name": "新账户", "region_id": 1, "balance": 0}, "account:create ← ROUTE_MAP(无POST路由?)"),
    ("GET",  "/api/accounts/1", None, "account:get"),
    ("GET",  "/api/accounts/1/transactions", None, "account:transactions"),
    ("POST", "/api/accounts/1/transactions", {"account_id": 1, "trans_type": "income", "amount": 500, "category": "测试"}, "account:add-transaction ← ROUTE_MAP(实际POST /transactions)"),
    ("POST", "/api/accounts/transactions", {"account_id": 1, "trans_type": "income", "amount": 500, "category": "测试"}, "cloud实际 add-transaction"),
    ("GET",  "/api/accounts/years", None, "account:years ← ROUTE_MAP(无路由?)"),
    ("GET",  "/api/announcements/active", None, "announcement:active-list ← ROUTE_MAP(无路由?)"),
    ("GET",  "/api/reports/land-area", None, "report:land-area"),
    ("GET",  "/api/reports/land-area-by-region", None, "report:land-area-by-region"),
    ("GET",  "/api/audit", None, "audit:list ← ROUTE_MAP(无路由?)"),
    ("GET",  "/api/notifications", None, "notification:list ← ROUTE_MAP(无路由?)"),
    ("POST", "/api/notifications/1/read", None, "notification:mark-read ← ROUTE_MAP(无路由?)"),
    ("GET",  "/api/auth/users", None, "auth:list-users ← ROUTE_MAP(无路由?)"),
    ("POST", "/api/auth/users/1/reset-password", None, "auth:reset-password ← ROUTE_MAP(无路由?)"),
    ("GET",  "/api/backup/info", None, "db:info ← ROUTE_MAP(无路由?)"),
    ("GET",  "/api/excel/export", None, "excel:export"),
]

print("\n===== ROUTE_MAP 端点探测 =====")
for method, path, body, label in PROBES:
    st, note, _ = req(method, path, body, token)
    flag = "OK " if st == 200 else "FAIL"
    print(f"{flag} [{st}] {method:6s} {path:45s} {label}\n     {note[:110]}")

# 3. 关键：contract:get 是否返回 items / total_cost / approval_status
print("\n===== contract:get 字段完整性 =====")
st, _, raw = req("GET", "/api/contracts/1", None, token)
if st == 200:
    j = json.loads(raw)
    need = ["items", "total_cost", "expected_income", "approval_status", "approved_by", "approved_at", "progress", "created_by", "updated_by"]
    missing = [k for k in need if k not in j]
    print("返回字段:", sorted(j.keys()))
    print("缺失(桌面端 Contract 类型必需):", missing)
    st2, _, raw2 = req("GET", "/api/contracts?limit=200", None, token)
    j2 = json.loads(raw2)
    print("list 分页形态:", list(j2.keys()) if isinstance(j2, dict) else f"裸数组[{len(j2)}]")
    if isinstance(j2, dict) and "items" in j2:
        it = j2["items"][0]
        m2 = [k for k in need if k not in it]
        print("list[0] 缺失字段:", m2)
