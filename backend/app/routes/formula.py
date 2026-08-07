"""公式计算 + 日志"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
import math
from ..database import get_db
from ..models import FormulaLog, Region
from ..services.formula import calculate_formulas, FormulaInput
from ..auth import get_current_user

router = APIRouter()


class CalcRequest(BaseModel):
    region_id: int
    population: float
    talent_population: float
    carbon_emissions: float
    supply_quantity: float = 0
    demand_quantity: float = 0
    prev_avg_price: float = 0
    current_avg_price: float = 0
    base_cost: float = 0
    base_profit: float = 0
    infra_employment_bonuses: list = []
    infra_population_delta: float = 0
    population_capacity: float = 10000
    base_growth_rate: float = 0.03
    infra_carbon_reduction: float = 0


@router.post("/calculate")
def calculate(req: CalcRequest, db: Session = Depends(get_db), _=Depends(get_current_user)):
    input_data = FormulaInput(**req.model_dump())
    output = calculate_formulas(input_data)

    # 保存日志
    max_round = db.query(FormulaLog).filter(
        FormulaLog.region_id == req.region_id
    ).count()
    log = FormulaLog(
        region_id=req.region_id,
        round=max_round + 1,
        input_population=req.population,
        input_talent=req.talent_population,
        input_carbon=req.carbon_emissions,
        input_supply=req.supply_quantity,
        input_demand=req.demand_quantity,
        input_price_avg=req.current_avg_price,
        output_happiness=output.happiness,
        output_base_price=output.base_price,
        output_sell_price=output.sell_price,
        output_employment_rate=output.total_employment_rate,
        output_population_next=round(output.next_population),
    )
    db.add(log)

    # 更新区域
    region = db.query(Region).filter(Region.id == req.region_id).first()
    if region:
        region.current_happiness = output.happiness
        region.current_employment_rate = output.total_employment_rate
        region.population = round(output.next_population)

    db.commit()
    return output.__dict__


@router.get("/logs/{region_id}")
def formula_logs(region_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(FormulaLog).filter(
        FormulaLog.region_id == region_id
    ).order_by(FormulaLog.round.asc()).all()
