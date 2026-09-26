import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.ingestion.ingest import ingest_teams_and_players, ingest_player_stats, ingest_fixtures

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def run_full_ingestion():
    try:
        await ingest_teams_and_players()
        await ingest_player_stats()
        await ingest_fixtures()
        logger.info("Scheduled ingestion completed successfully")
    except Exception:
        logger.exception("Scheduled ingestion failed")


def start_scheduler():
    scheduler.add_job(run_full_ingestion, "interval", hours=3, id="full_ingestion", replace_existing=True)
    scheduler.start()
