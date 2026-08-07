"""所有数据库模型 — 对应 Electron 版的 12 张表 + 新增 SaaS 字段"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, ForeignKey, DateTime, Text, Index, Boolean
)
from sqlalchemy.orm import relationship
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
    status = Column(String, default="draft")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
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
    sort_order = Column(Integer, default=0)

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
        return round(self.quantity * self.unit_price * self.tax_rate, 2)

    @property
    def total(self):
        return self.quantity * self.unit_price * (1 + self.tax_rate)

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
    created_at = Column(DateTime, default=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
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
