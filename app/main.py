from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1 import (
    health, players, optimize, rating, transfers, lineup, scores,
    fixture_plan, chip_plan, captain_history, mini_league, projection, template,
)
from app.core.scheduler import scheduler, start_scheduler, run_full_ingestion
from app.core.auth import verify_api_key
import logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await run_full_ingestion()
    except Exception:
        logger.exception("Startup ingestion failed — continuing with existing data")
    start_scheduler()
    yield
    scheduler.shutdown()


app = FastAPI(title="FPL Decision-Support Tool", lifespan=lifespan)

# Allow any origin so the API remains usable if the frontend is ever served
# separately (e.g. during local development or a future deployment split).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["X-API-Key"],
)

app.include_router(health.router, prefix="/api/v1")
app.include_router(players.router, prefix="/api/v1", dependencies=[Depends(verify_api_key)])
app.include_router(optimize.router, prefix="/api/v1", dependencies=[Depends(verify_api_key)])
app.include_router(rating.router, prefix="/api/v1", dependencies=[Depends(verify_api_key)])
app.include_router(transfers.router, prefix="/api/v1", dependencies=[Depends(verify_api_key)])
app.include_router(lineup.router, prefix="/api/v1", dependencies=[Depends(verify_api_key)])
app.include_router(scores.router, prefix="/api/v1", dependencies=[Depends(verify_api_key)])
app.include_router(fixture_plan.router, prefix="/api/v1", dependencies=[Depends(verify_api_key)])
app.include_router(chip_plan.router, prefix="/api/v1", dependencies=[Depends(verify_api_key)])
app.include_router(captain_history.router, prefix="/api/v1", dependencies=[Depends(verify_api_key)])
app.include_router(mini_league.router, prefix="/api/v1", dependencies=[Depends(verify_api_key)])
app.include_router(projection.router, prefix="/api/v1", dependencies=[Depends(verify_api_key)])
app.include_router(template.router, prefix="/api/v1", dependencies=[Depends(verify_api_key)])

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
