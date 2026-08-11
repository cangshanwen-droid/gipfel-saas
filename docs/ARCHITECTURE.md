# Gipfel 管理系统 — 架构文档

> 维护日期：2026-08-11（v1.3.0）。本文件是系统的唯一权威架构说明，
> 新增/修改模块时必须同步更新。

## 1. 系统拓扑

```
用户（浏览器 / Electron 桌面端）
    │
    ▼
┌──────────────── 80 (HTTP) ────────────────┐
│ Nginx：全部 301 → HTTPS（强制加密）          │
└──────────────── 443 (HTTPS) ───────────────┘
    │                        │
    ▼                        ▼
 :8000 gipfel-api        :8001 stock-api
 (软件主系统 v2.0.0)      (股票交易 v1.1)
   gipfel.db               stocks.db
   (SQLite WAL)            (SQLite)
    ▲                        ▲
    └──── 仅本机回源（ufw 只放行 80/443/22，8000/8001 公网不可直连）
```

- **部署主机**：腾讯云 Lighthouse `106.54.26.86`（Ubuntu 20.04，Python 3.8，2C2G）
- **服务管理**：systemd（gipfel-api.service / stock-api.service），`Restart=always`
- **TLS**：自签名证书，桌面端 `setCertificateVerifyProc` 特判放行

## 2. 数据模型

### gipfel.db（主系统，SQLite WAL）
| 表 | 说明 |
|----|------|
| users | 软件账号（bcrypt，org_id 组织绑定，company_id 公司绑定） |
| organizations | 组织（公司 1:1 同步创建） |
| regions | 区域（人口/人才/碳排/增长率） |
| companies | 公司（上市可自动生成股票代码） |
| contract_types | 合同类型（1-8：基建/开采/采购/劳动力/投资/拨款/销售/减碳） |
| contracts | 合同主表（含 **version 乐观锁列**、approval 状态机、org_id） |
| contract_items | 合同明细（tax_rate 百分比口径 /100） |
| contract_versions | 合同编辑历史快照 |
| region_accounts | 区域资金账户（balance 原子 UPDATE） |
| account_transactions | 资金流水（income/expense） |
| announcements / notifications / audit_logs | 公告/通知/审计 |
| schema_migrations | 迁移版本表（当前 23） |

### stocks.db（股票系统）
| 表 | 说明 |
|----|------|
| users | 交易账户（**无密码**——统一账号源在 gipfel-api，本地零密码存储） |
| stocks | 股票（symbol/current_price/涨跌幅/碳排等） |
| orders | 订单（buy/sell，原子扣款） |
| portfolios | 持仓（加权均价） |

## 3. 认证与安全

### 统一账号（单一账号源 = gipfel-api）
```
桌面登录（bcrypt 校验）
  → StockMarketPage 调 stock-api /auth/login
  → stock-api 转发 gipfel-api /api/auth/login 验证（本机回环 127.0.0.1:8000）
  → 验证通过 → stock-api 本地 upsert（仅交易数据，密码列空）
  → 返回 token（TOKENS 内存映射）→ iframe ?token=&username= 免登录
```
- 改密/删用户/角色变更 → 只操作软件端，股票端登录时实时跟随
- 注册双端关闭（软件端需 X-Admin-Key；股票端恒 403）

### 交易鉴权（v1.3.0 新增）
- `/orders` `/portfolio` `/fund-accounts` 必须带 `Authorization: Bearer <token>`
- token 由登录生成，存内存 `TOKENS` 映射
- 请求身份必须与 token 一致（admin 可代操作，其余 403）

### 其他安全措施
- JWT（SECRET_KEY 强随机，HS256，8h 过期）
- 密码 bcrypt(12) / PBKDF2(29000)
- 桌面端：preload IPC 白名单 + 会话校验 + will-navigate hostname 精确匹配 + safeStorage
- 登录限流、审计留痕、X-Admin-Key 双因子（管理端点）
- ufw 最小暴露

## 4. 数据一致性保障（关键设计）

| 场景 | 机制 |
|------|------|
| 合同编号并发 | `seq + 随机后缀` + IntegrityError 重试（6 次） |
| 资金扣款并发 | `UPDATE ... SET balance = balance + ? WHERE ... AND balance + ? >= 0`（原子 + 防透支），**禁止 ORM 覆盖** |
| 合同编辑并发 | **乐观锁**：version 列 + `expected_version` 校验（不匹配 409） |
| 提交冲突 | WAL + busy_timeout + commit_with_retry（50ms→100ms 退避） |
| 桌面本地库 | 原子落盘（tmp+rename）+ .bak 回退链 + backups/ 目录 |
| 云端备份 | cron.d 每日 04:30，保留 7 天 |
| 完整性校验 | sql.js 用 `PRAGMA integrity_check`（**无 checkIntegrity() 方法**） |

## 5. 桌面端（Electron）

- **技术栈**：Electron + React + sql.js + electron-vite + vitest
- **数据流**：固定云端模式（isCloudMode 恒 true）——本地库只存认证缓存，业务数据全走 REST
- **迁移**：schema_migrations v1~v23（双端独立维护，改字段必须双端同步）
- **自动更新**：electron-updater + GitHub Releases（latest.yml 为真源）
- **打包**：electron-builder，artifactName 必须纯 ASCII（中文名被 sanitize 致 404）

## 6. 测试体系

| 套件 | 内容 | 运行 |
|------|------|------|
| vitest（桌面端） | 69 项（权限/审批流/批量审批/验收） | `npm test` |
| verify-local | 迁移 v1~23 + CRUD + seed（11 项） | `npm run verify` |
| verify-cloud | 云端 API 冒烟（5 项） | 同上 |
| verify-ui | UI 静态检查（9 项） | 同上 |
| pytest（云端后端） | 10 项（认证/并发编号/资金原子/组织同步/税率） | 服务器 `venv/bin/python -m pytest tests/` |

## 7. 已知限制（诚实清单）

- 自签名证书（无商业信任）——企业分发需商业证书
- 服务器 2G 内存，高并发可能 OOM
- 双 SQLite 无跨库事务（合同资金与股票资金两套账）
- 商业签名证书缺失（SmartScreen 提示"未知发布者"）
- 服务器到期 2026-09-10（待续费）
