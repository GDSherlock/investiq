"""GET /market-data/{series} — time-series market data."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import MarketDataPoint

router = APIRouter()


@router.get("/market-data/{series}")
async def get_market_data(
    series: str,
    limit: int = Query(default=100, le=1000),
    db: Session = Depends(get_db),
):
    """Get time-series market data for a given series."""
    points = (
        db.query(MarketDataPoint)
        .filter(MarketDataPoint.series_id == series)
        .order_by(MarketDataPoint.timestamp.desc())
        .limit(limit)
        .all()
    )

    return {
        "series": series,
        "count": len(points),
        "data": [
            {
                "timestamp": p.timestamp,
                "value": p.value,
                "source": p.source,
            }
            for p in points
        ],
    }
