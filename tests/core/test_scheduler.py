from unittest.mock import AsyncMock, MagicMock, patch

from app.core.scheduler import run_full_ingestion, start_scheduler


async def test_run_full_ingestion_calls_all_three_ingest_functions():
    with patch("app.core.scheduler.ingest_teams_and_players", new=AsyncMock()) as mock_teams, \
         patch("app.core.scheduler.ingest_player_stats", new=AsyncMock()) as mock_stats, \
         patch("app.core.scheduler.ingest_fixtures", new=AsyncMock()) as mock_fixtures:
        await run_full_ingestion()

    mock_teams.assert_awaited_once()
    mock_stats.assert_awaited_once()
    mock_fixtures.assert_awaited_once()


async def test_run_full_ingestion_logs_success(caplog):
    import logging
    with patch("app.core.scheduler.ingest_teams_and_players", new=AsyncMock()), \
         patch("app.core.scheduler.ingest_player_stats", new=AsyncMock()), \
         patch("app.core.scheduler.ingest_fixtures", new=AsyncMock()), \
         caplog.at_level(logging.INFO, logger="app.core.scheduler"):
        await run_full_ingestion()

    assert any("completed successfully" in r.message for r in caplog.records)


async def test_run_full_ingestion_swallows_exception_and_logs_error(caplog):
    import logging
    with patch("app.core.scheduler.ingest_teams_and_players", new=AsyncMock(side_effect=RuntimeError("network down"))), \
         patch("app.core.scheduler.ingest_player_stats", new=AsyncMock()), \
         patch("app.core.scheduler.ingest_fixtures", new=AsyncMock()), \
         caplog.at_level(logging.ERROR, logger="app.core.scheduler"):
        await run_full_ingestion()  # must not raise

    assert any("failed" in r.message for r in caplog.records)


def test_start_scheduler_registers_job_and_starts():
    mock_scheduler = MagicMock()
    with patch("app.core.scheduler.scheduler", mock_scheduler):
        start_scheduler()

    mock_scheduler.add_job.assert_called_once_with(
        run_full_ingestion, "interval", hours=3, id="full_ingestion", replace_existing=True
    )
    mock_scheduler.start.assert_called_once()
