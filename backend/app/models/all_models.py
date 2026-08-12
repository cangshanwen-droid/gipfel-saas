"""所有数据库模型 — 对应 Electron 版的 12 张表 + 新增 SaaS 字段"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, ForeignKey, DateTime, Text, Index, Boolean, text
)
from sqlalchemy.orm import relationship, object_session
from ..database import Base

# ── 1. regions ───────────────────────────────────
class Region(Base):
    __tablename__ = "regions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    population = Column(Float, default=0)
    talent_population = Column(Float, default=0)
    carbon_emissions = Column(Float, default=0)
    population_capacity = Column(Float, default=10000)
    base_growth_rate = Column(Float, default=0.03)
    current_happiness = Column(Float, nullable=True)
    current_employment_rate = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # SaaS: 属于哪个组织
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, default=None)

# ── 2. companies ─────────────────────────────────
class Company(Base):
    __tablename__ = "companies"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    region = Column(String, default="")
    company_type = Column(String, default="")
    contact = Column(String, default="")
    phone = Column(String, default="")
    email = Column(String, default="")
    address = Column(String, default="")
    notes = Column(Text, default="")
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, default=None)

    __table_args__ = (Index("idx_companies_region", "region"),)

# ── 3. contract_types ────────────────────────────
class ContractType(Base):
    __tablename__ = "contract_types"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(String, default="")
    color = Column(String, default="#1890ff")
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# ── 4. contracts ─────────────────────────────────
class Contract(Base):
    __tablename__ = "contracts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_no = Column(String, unique=True, nullable=False)
    contract_name = Column(String, nullable=False)
    contract_type_id = Column(Integer, ForeignKey("contract_types.id"), nullable=True)
    party_a = Column(String, default="")
    party_b_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    party_b_name = Column(String, default="")
    region_id = Column(Integer, ForeignKey("regions.id"), nullable=True)
    sign_date = Column(String, nullable=True)
    status = Column(String, default="draft")  # v1.3.1 金融化：draft/active/executing/completed/terminated
    notes = Column(Text, default="")
    # ── P0-2 补字段：与桌面端 Contract 类型对齐 ──
    total_cost = Column(Float, default=0)          # 合同级总成本（投资合同=投资总额）
    expected_income = Column(Float, default=0)     # 合同级预期收益
    approval_status = Column(String, default="none")  # v1.3.1 弃用（保留列兼容历史数据）
    approved_by = Column(String, default="")
    approved_at = Column(String, nullable=True)
    progress = Column(Float, default=0)
    # ── v1.3.1 金融化新字段 ──
    contract_amount = Column(Float, default=0)     # 合同金额（总投资额）
    contract_period = Column(String, default="")   # 合同期限（如：3年）
    owner = Column(String, default="")             # 负责人
    attachment = Column(String, default="")        # 附件名/路径
    created_by = Column(String, default="")
    updated_by = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # ── v1.3.0 乐观锁：并发编辑防后写覆盖先写（前端传 expected_version 时校验，自增）──
    version = Column(Integer, default=1, nullable=False)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, default=None)

    items = relationship("ContractItem", back_populates="contract", cascade="all, delete-orphan")
    contract_type = relationship("ContractType")
    region = relationship("Region")
    party_b = relationship("Company")

    __table_args__ = (
        Index("idx_contracts_region", "region_id"),
        Index("idx_contracts_status", "status"),
        Index("idx_contracts_party_b", "party_b_id"),
    )

# ── 5. contract_items ────────────────────────────
class ContractItem(Base):
    __tablename__ = "contract_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(Integer, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    item_name = Column(String, nullable=False)
    quantity = Column(Float, default=1)
    unit_price = Column(Float, default=0)
    land_area = Column(Float, default=0)
    tax_rate = Column(Float, default=0)
    skill_level = Column(Float, default=0)
    carbon_factor = Column(Float, default=0)
    # P0-2 补字段：明细级金额（投资合同=投资总额/预期收益、拨款合同=拨款金额）
    total_cost = Column(Float, nullable=True, default=None)      # 投资金额（原总成本）
    expected_income = Column(Float, nullable=True, default=None) # 预期收益
    sort_order = Column(Integer, default=0)
    # ── v1.3.1 金融化：投资项目字段（全面替代工程类数量/单价明细）──
    investment_type = Column(String, default="")      # 股权投资/债权投资/基金投资/项目投资/其他
    equity_ratio = Column(Float, default=0)           # 占股比例（%）
    # v1.3.1-2 用户拍板替换：预期收益率/预期收益/投资期限 → 股数/股价
    shares = Column(Integer, default=0)               # 股数（投资股票数量）
    price = Column(Float, default=0)                  # 股价（每股价格）

    contract = relationship("Contract", back_populates="items")

    # 计算字段 (Python property，对应 SQLite 的 GENERATED ALWAYS AS)
    @property
    def amount(self):
        return self.quantity * self.unit_price

    @property
    def total_land_area(self):
        return self.quantity * self.land_area

    @property
    def tax_amount(self):
        # P0-3 税率口径修复：tax_rate 为百分比（13=13%），与桌面端 v20 生成列一致
        return round(self.quantity * self.unit_price * self.tax_rate / 100, 2)

    @property
    def total(self):
        # P0-3 税率口径修复：含税总价 = 不含税 × (1 + 税率/100)
        return self.quantity * self.unit_price * (1 + self.tax_rate / 100)

    __table_args__ = (Index("idx_contract_items_contract", "contract_id"),)

# ── 6. infrastructure_types ──────────────────────
class InfrastructureType(Base):
    __tablename__ = "infrastructure_types"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    category = Column(String, default="民生配套")
    default_land_area = Column(Float, default=0)
    unit = Column(String, default="座")
    description = Column(String, default="")
    price = Column(Float, default=0)
    revenue_index = Column(Float, default=0)
    recommended_ratio = Column(Float, default=0)
    maintenance_fee = Column(Float, default=0)
    population_addition = Column(Float, default=0)
    talent_addition = Column(Integer, default=0)
    happiness_index = Column(Float, default=0)
    h_bonus = Column(Float, default=0)
    carbon_reduction = Column(Float, default=0)
    activation_price = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

# ── 7. formula_logs ──────────────────────────────
class FormulaLog(Base):
    __tablename__ = "formula_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    region_id = Column(Integer, ForeignKey("regions.id"), nullable=False)
    round = Column(Integer, default=1)
    calculated_at = Column(DateTime, default=datetime.utcnow)
    input_population = Column(Float, nullable=False)
    input_talent = Column(Float, nullable=False)
    input_carbon = Column(Float, nullable=False)
    input_supply = Column(Float, default=0)
    input_demand = Column(Float, default=0)
    input_price_avg = Column(Float, default=0)
    output_happiness = Column(Float, nullable=False)
    output_base_price = Column(Float, default=0)
    output_sell_price = Column(Float, default=0)
    output_employment_rate = Column(Float, nullable=False)
    output_population_next = Column(Float, nullable=False)

    __table_args__ = (Index("idx_formula_logs_region", "region_id"),)

# ── 8. infra_employment_bonuses ──────────────────
class InfraEmploymentBonus(Base):
    __tablename__ = "infra_employment_bonuses"
    id = Column(Integer, primary_key=True, autoincrement=True)
    item_name = Column(String, unique=True, nullable=False)
    bonus = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

# ── 9. users ─────────────────────────────────────
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    salt = Column(String, default="")
    role = Column(String, default="user")  # admin / user
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True, default=None)
    # v1.3.1-3 股票账户类型：1=可用资金可修改（代表账户）/ 0=不可修改（主席审计账户，初始100万锁定）
    stock_adjustable = Column(Integer, default=1)
    last_login = Column(String, nullable=True)  # 最近登录时间（系统概览活跃用户统计）
    created_at = Column(DateTime, default=datetime.utcnow)

    # v1.3.0 多公司绑定：用户 ↔ 公司 多对多（主席可管多家公司）
    company_links = relationship(
        "UserCompany", backref="user", cascade="all, delete-orphan",
        primaryjoin="User.id == UserCompany.user_id")

    @property
    def company_ids(self) -> list:
        """该用户绑定的全部公司 id（多对多；兼容 org_id 单值逻辑）"""
        ids = [c.company_id for c in (self.company_links or [])]
        if not ids and self.org_id:
            ids = [self.org_id]
        return ids

    @property
    def company_org_ids(self) -> list:
        """该用户绑定公司的 org_id 列表（多对多；用于合同隔离 IN 查询）。
        UserCompany.company_id 是 companies.id；org_id 是 organizations.id。
        旧数据 org_id 单值：该值本身即组织 id。"""
        ids = [c.company_id for c in (self.company_links or [])]
        if not ids:
            if self.org_id:
                return [self.org_id]
            return []
        # 多对多：ORM 查询 companies.org_id（公司→组织映射；IN 用 ORM 原生绑定）
        try:
            session = object_session(self)
            if session is None:
                return ids  # 无法查询时退回 company_id
            from .all_models import Company
            rows = session.query(Company.org_id).filter(
                Company.id.in_(ids), Company.org_id.isnot(None)).all()
            orgs = [r[0] for r in rows]
            return orgs if orgs else ids
        except Exception:
            return ids

# ── 10. region_accounts ──────────────────────────
class RegionAccount(Base):
    __tablename__ = "region_accounts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    region_id = Column(Integer, ForeignKey("regions.id"), nullable=False)
    account_name = Column(String, nullable=False)
    balance = Column(Float, default=0)
    is_master = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# ── 11. account_transactions ─────────────────────
class AccountTransaction(Base):
    __tablename__ = "account_transactions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("region_accounts.id"), nullable=False)
    trans_type = Column(String, nullable=False)  # income / expense
    category = Column(String, default="")
    amount = Column(Float, nullable=False)
    description = Column(String, default="")
    fiscal_year = Column(Integer, nullable=True)
    # 与桌面端对齐：合同联动流水标记（幂等防重复入账）
    operator = Column(String, default="")
    contract_id = Column(Integer, nullable=True)
    source_type = Column(String, default="manual")  # manual / contract
    # v1.3.0 跨库资金桥幂等：订单号唯一（并发同 key 只扣一次——DB 级唯一约束，
    # 内存字典有竞态，曾致并发同 key 双扣）
    idempotency_key = Column(String, default="", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        # 部分唯一索引：仅对带 key 的流水生效（manual 类流水 key 为空不约束）
        Index("uq_account_txn_idem_key", "idempotency_key", unique=True,
              sqlite_where=text("idempotency_key != ''")),
        Index("idx_trans_account", "account_id"),
        Index("idx_trans_fiscal", "fiscal_year"),
    )

# ── 12. schema_migrations (元数据) ───────────────
class SchemaMigration(Base):
    __tablename__ = "schema_migrations"
    version = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    applied_at = Column(DateTime, default=datetime.utcnow)

# ── NEW: organizations (SaaS 多租户) ─────────────
class Organization(Base):
    __tablename__ = "organizations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    plan = Column(String, default="free")  # free / pro / enterprise
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ── P0-1 新增：合同版本历史（对齐桌面端 contract_versions 表）─────
class ContractVersion(Base):
    __tablename__ = "contract_versions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(Integer, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    snapshot = Column(Text, nullable=False)        # JSON：字段快照
    changed_fields = Column(Text, default="[]")    # JSON：变更字段列表
    created_by = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_contract_versions_contract", "contract_id"),
    )


# ── P0-1 新增：公告（对齐桌面端 announcements 表）─────
class Announcement(Base):
    __tablename__ = "announcements"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    region_id = Column(Integer, ForeignKey("regions.id"), nullable=True)
    priority = Column(String, default="normal")  # high / normal / low
    created_by = Column(String, default="")
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── P0-1 新增：通知中心（对齐桌面端 notifications 表）─────
class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False)
    content = Column(Text, default="")
    type = Column(String, default="system")  # approval / announcement / transaction / system
    link = Column(String, default="")
    read = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_notifications_user", "user_id", "read"),
    )


# ── P0-1 新增：审计日志（对齐桌面端 audit_logs 表）─────
class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, default="")
    role = Column(String, default="")
    action = Column(String, nullable=False)
    target = Column(String, default="")
    target_id = Column(Integer, nullable=True)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    ip = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    result = Column(String, default="success")

    __table_args__ = (
        Index("idx_audit_timestamp", "timestamp"),
        Index("idx_audit_username", "username"),
        Index("idx_audit_action", "action"),
    )


# ── v1.3.0 多公司绑定：用户 ↔ 公司 多对多关联表 ──
# 主席（operator）可管多家公司：user_companies 记录 user 与 company 的关联。
# 代表（rep）仍单公司（取第一行，兼容 org_id 单值逻辑）。
class UserCompany(Base):
    __tablename__ = "user_companies"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("uq_user_company", "user_id", "company_id", unique=True),)
