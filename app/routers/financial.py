from datetime import datetime

from fastapi import APIRouter, Request

from app.models.schemas import (
    DebtPaymentRequest,
    DebtSummaryResponse,
    MonthlyReport,
)

router = APIRouter(prefix="/financial", tags=["financial"])


@router.get("/report", response_model=MonthlyReport)
async def financial_report(
    request: Request,
    month: int | None = None,
    year: int | None = None,
    compare: bool = False,
):
    graph = request.app.state.retrieval.graph
    now = datetime.utcnow()
    m = month or now.month
    y = year or now.year

    if compare:
        report = await graph.query_month_comparison(m, y)
    else:
        report = await graph.query_monthly_report(m, y)

    return MonthlyReport(**report)


@router.get("/debts", response_model=DebtSummaryResponse)
async def debt_summary(request: Request):
    graph = request.app.state.retrieval.graph
    summary = await graph.query_debt_summary()
    return DebtSummaryResponse(**summary)


@router.post("/debts/payment")
async def record_debt_payment(req: DebtPaymentRequest, request: Request):
    graph = request.app.state.retrieval.graph
    result = await graph.record_debt_payment(
        person=req.person,
        amount=req.amount,
        direction=req.direction,
    )
    return result


@router.get("/alerts")
async def spending_alerts(request: Request):
    graph = request.app.state.retrieval.graph
    alerts_text = await graph.query_spending_alerts()
    return {"alerts": alerts_text or "No spending alerts."}
