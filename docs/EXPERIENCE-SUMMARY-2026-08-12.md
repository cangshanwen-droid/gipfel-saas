# Gipfel 项目经验总结 — 2026-08-12（上线冲刺 + 全面审核收尾）

> 本文档沉淀本次上线冲刺与多维审核（安全/业务/工程三路并行）的全部经验，
> 供后续维护与二次开发直接复用。

---

## 一、项目现状（终态可交付）

| 维度 | 状态 |
|------|------|
| 云端服务 | gipfel-api :8000（2.0.0）+ stock-api :8001（1.1）+ nginx（80→301→443）@ 106.54.26.86 |
| 数据库 | gipfel.db（WAL+busy_timeout 5000）/ stocks.db（WAL）双库 integrity ok |
| 数据终态 | gipfel：公司 4 / 用户 4 / 合同 1（铁矿开采）/ 组织 5 / 公告 0 / 流水 0；stock：用户 1 / 订单 6 / 余额 100000 |
| 备份链 | 每日 03:00 cron + 保留 7 天 + 双库（13:34 最新纯净备份） |
| 桌面端 | 安装版 180MB（含全部修复）/ 本地 DB v25 / 快捷方式正常 |
| 代码仓库 | contract-manager `afcbb04` / gipfel-saas `99b4c41` / stock-analysis `1274f7e` 全干净 |

---

## 二、本轮修复清单（三路审核 2026-08-12）

### 安全维度（P0×5 + P1 系列）
1. **批量合同操作零鉴权** → batch_approve 加角色校验 + 公司隔离 + 禁删保护 + 流水清理
2. **单条删除合同无校验** → delete_contract 加角色 + 公司归属（operator 限绑定公司）
3. **Excel 全库导出** → 仅 admin/operator 可导出（rep 403）
4. **资金桥 sell 无条件加款** → 仅内部密钥可调（JWT 用户 403「加款操作仅限内部服务调用」）
5. **财务账户零公司隔离** → `_user_region_ids` 辅助函数全端点过滤（rep 仅见本公司区域）
6. P1：companies/regions/announcements 写权限 / 密码复杂度（change-password 含字母数字）/ JWT sub TypeError / 审计 f-string→json.dumps

### 业务/数据维度（P0×5）
1. **买卖失败补偿双重执行**（buy 凭空加钱 / sell 凭空扣钱）→ 删 db2 手动补偿，rollback 自动回退
2. **幂等 SELECT-then-write 非原子** → IntegrityError 捕获回读原订单返回幂等结果
3. **并发卖超**（读-改-写非原子）→ 条件 UPDATE `quantity-? WHERE quantity>=?` + rowcount 校验
4. **commit_with_retry 静默丢写**（rollback 重试空事务=200 但账没动）→ 不再 rollback，直接重试 commit
5. **DDL 漂移**（company_accounts 从未在 init_db 建表）→ init_db + startup 迁移补表补列
6. P1：用户解绑公司残留 company_id → 非 admin 解绑清空

### 工程维度（P0×2 + P1）
1. **编辑合同保存清空投资字段**（前端只发 7 旧字段）→ 前端透传全字段 + 云端 Optional 继承 + 本地 INSERT 补列
2. **卖出补偿逻辑反向**（与业务 P0-1 同根）→ 已随补偿修复解决
3. P1：公司/区域 CRUD IPC 无权限 → requirePermission（COMPANY_MANAGE/REGION_MANAGE 权限点）

---

## 三、核心经验（复用价值最高）

### 资金安全类（金钱相关，必须原子）
- **SQLite 事务内失败 = rollback 已自动回退**——绝不在 rollback 后再手动补偿（双重执行 = 凭空加/扣钱）。要补偿就回读数据库当前状态决定，不要凭内存值。
- **并发防超卖**：`UPDATE ... SET qty=qty-? WHERE qty>=?` + rowcount 检查，比 SELECT-then-UPDATE 可靠。
- **幂等**：DB 级部分唯一索引（空 key 不约束）+ INSERT 撞索引后回读原记录返回幂等结果。
- **commit 重试**：绝不 rollback 后重试（提交空事务=静默丢写）。直接重试 commit（WAL busy 时数据仍在）。
- **DDL 漂移**：init_db 建表必须与运行 SQL 用到的表/列完全一致；startup 迁移仿照幂等索引模式补列。

### 权限隔离类
- **读有隔离写没有 = 隐形漏洞**——create/update/delete 都要校验归属（不止 list/get）。
- **导出入口是数据泄露面**——Excel 全量导出要限角色。
- **"自己给自己加钱"的端点**也是漏洞（资金桥 sell），内部回环调用必须 X-Internal-Key。
- **用户解绑**要联动清空下游关联（company_id 残留 = 继续操作原公司）。

### 验证纪律类
- **三路并行审核**（安全/业务/工程）发现的问题远超单路——业务 agent 抓资金 bug、工程 agent 抓数据丢失、安全 agent 抓越权。
- **fresh 复核**：`hermes-verify-` 前缀 + tempfile 路径 + 全新文件名，源码不变量 + 云端实测 + 终态 + 零残留四层。
- **脚本 bug 与产品 bug 要区分**：断言写错/解析 bug/时序假设错都会误报——先查服务端日志/数据库实况再下结论。
- **scp 同名文件注意路径**：`auth.py` 在 app 根（JWT 工具）vs routes/（认证路由）——覆盖错文件直接 502。
- **electron-builder 时间戳**保留旧值但内容已更新——验证产物要 grep 编译产物，别信时间戳。

### 部署类
- **SSH 内联 python3 -c 引号嵌套必失败** → scp 脚本正解。
- **API DELETE 软删不可靠**（completed/active 禁删 + 测试残留）→ 物理清理用 sqlite 直连脚本。
- **NSIS 静默安装 System.dll 崩溃无提示** → 事件日志 Application Error 1000；手动 cp win-unpacked 最稳。

---

## 四、遗留事项（非阻塞，需用户决策）

1. **服务器到期 2026-09-10**——续费前必须导出云端+桌面 DB（需成本，暂缓）
2. **stock 订单 6 条**（admin 实测买卖历史）——保留（审计价值）或删除（更纯净），待用户确认
3. **NSIS System.dll 崩溃根因**未根除（重建规避）——后续打包留意
4. **已确认的 P2 级**（低风险，可后续处理）：AUTH_LIST_USERS 匿名返回、CORS 通配、自动更新无签名校验、密码过期策略、Excel 导入无类型校验、2GB 内存高并发 OOM

---

## 五、验证证据链（全部实测）

| 测试 | 结果 | 时间 |
|------|:--:|------|
| 账号注册核查（密码规则/角色枚举） | 13/13 | 12:1x |
| 并发实测（登录/建合同/买卖/幂等/隔离） | 11/11 | 12:2x |
| 三路审核修复回归（rep 越权矩阵/资金桥/导出） | 13/13 | 12:4x |
| 前端投资字段修复（编辑保存/继承） | 3/3 | 12:5x |
| 业务回归（建合同/状态机/operator 隔离） | 8/8 | 12:5x |
| 审核修复 fresh 复核 v3 | 20/20 | 12:5x |
| 资金 P0 修复（并发幂等/卖超/回补） | 14/14 | 13:0x |
| 最终全面检查（服务/数据/备份/桌面/git） | 14/14 | 13:3x |
| 桌面端 | typecheck 0 + vitest 69/69 | 12:5x |
