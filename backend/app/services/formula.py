"""Gipfel 公式引擎 — 从 JS 原样移植到 Python"""
import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class FormulaInput:
    population: float
    talent_population: float
    carbon_emissions: float
    supply_quantity: float = 0
    demand_quantity: float = 0
    prev_avg_price: float = 0
    current_avg_price: float = 0
    base_cost: float = 0
    base_profit: float = 0
    infra_employment_bonuses: list = None  # list of {name, bonus}
    infra_population_delta: float = 0
    population_capacity: float = 10000
    base_growth_rate: float = 0.03
    infra_carbon_reduction: float = 0
    region_id: Optional[int] = None

    def __post_init__(self):
        if self.infra_employment_bonuses is None:
            self.infra_employment_bonuses = []


@dataclass
class FormulaOutput:
    consumer_satisfaction: float
    price_sensitivity: float
    market_demand: float
    happiness: float
    base_price: float
    sell_price: float
    base_employment_rate: float
    infra_employment_bonus_total: float
    actual_infra_employment_bonus: float
    total_employment_rate: float
    next_population: float
    population_carbon: float = 0
    extraction_carbon: float = 0
    infra_carbon_reduction: float = 0
    remaining_extraction_carbon: float = 0
    total_carbon: float = 0


def calculate_formulas(input: FormulaInput) -> FormulaOutput:
    # 消费者满足度
    consumer_satisfaction = (
        input.supply_quantity / input.demand_quantity if input.demand_quantity > 0 else 0
    )

    # 价格敏感系数
    price_sensitivity = (
        1 - input.prev_avg_price / input.current_avg_price
        if input.current_avg_price > 0 else 0
    )

    # 市场需求量
    market_demand = price_sensitivity * input.population

    # 碳排放计算
    population_carbon = input.population * 10
    extraction_carbon = input.carbon_emissions
    infra_carbon_reduction = input.infra_carbon_reduction or 0
    remaining_extraction_carbon = max(0, extraction_carbon - infra_carbon_reduction)
    total_carbon = max(2000, population_carbon + remaining_extraction_carbon)

    # 幸福度
    talent_ratio = input.talent_population / input.population if input.population > 0 else 0
    carbon_per_capita = total_carbon / max(input.population, 1)

    happiness = (
        0.6 * consumer_satisfaction +
        0.1 * math.log10(input.population + 100) +
        2 * talent_ratio +
        0.2 * carbon_per_capita
    )
    clamped_happiness = max(1, min(100, happiness * 10))

    # 基准价格
    base_price = input.base_cost + input.base_profit

    # 商品成交价
    qd_max = input.population * 2
    sell_price = (
        base_price *
        (1 + clamped_happiness / 100) *
        (1 + (market_demand - input.supply_quantity) / max(qd_max, 1))
    )

    # 就业率
    base_employment_rate = 5 * math.log10(input.population + 100)
    infra_employment_bonus_total = sum(item.get("bonus", 0) for item in input.infra_employment_bonuses)
    actual_infra_employment_bonus = (
        25 * infra_employment_bonus_total / (infra_employment_bonus_total + 30)
    )
    total_employment_rate = base_employment_rate + actual_infra_employment_bonus

    # 人口迭代
    natural_growth = input.population * input.base_growth_rate * (clamped_happiness / 100)
    raw_growth = natural_growth + input.infra_population_delta
    capacity_factor = max(0, 1 - input.population / max(input.population_capacity, 1))
    population_change = raw_growth * capacity_factor
    next_population = min(input.population + population_change, input.population_capacity)

    return FormulaOutput(
        consumer_satisfaction=consumer_satisfaction,
        price_sensitivity=price_sensitivity,
        market_demand=market_demand,
        happiness=clamped_happiness,
        base_price=base_price,
        sell_price=sell_price,
        base_employment_rate=base_employment_rate,
        infra_employment_bonus_total=infra_employment_bonus_total,
        actual_infra_employment_bonus=actual_infra_employment_bonus,
        total_employment_rate=total_employment_rate,
        next_population=next_population,
        population_carbon=population_carbon,
        extraction_carbon=extraction_carbon,
        infra_carbon_reduction=infra_carbon_reduction,
        remaining_extraction_carbon=remaining_extraction_carbon,
        total_carbon=total_carbon,
    )
