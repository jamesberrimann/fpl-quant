from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import app.ingestion.fpl_client as fpl_client_module
from app.ingestion.fpl_client import (
    get_bootstrap_static,
    get_entry_picks,
    get_fixtures,
    get_gameweek_live,
)


@pytest.fixture(autouse=True)
def clear_fpl_cache():
    fpl_client_module._CACHE.clear()
    yield
    fpl_client_module._CACHE.clear()


def _ok(data):
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = data
    return r


def _http_error(status_code: int):
    r = MagicMock()
    r.raise_for_status.side_effect = httpx.HTTPStatusError(
        f"HTTP {status_code}",
        request=MagicMock(),
        response=MagicMock(status_code=status_code),
    )
    return r


def _make_client(*responses):
    """Build a mock httpx.AsyncClient context manager that returns responses in order."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=list(responses))
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    return mock_cm, mock_client


@pytest.fixture
def no_sleep():
    """Skip tenacity's exponential backoff sleep so retry tests run instantly."""
    with patch("asyncio.sleep", new_callable=AsyncMock):
        yield


# --- Happy path ---

async def test_get_bootstrap_static_returns_json():
    mock_cm, _ = _make_client(_ok({"teams": []}))
    with patch("app.ingestion.fpl_client.httpx.AsyncClient", return_value=mock_cm):
        result = await get_bootstrap_static()
    assert result == {"teams": []}


async def test_get_fixtures_returns_list():
    mock_cm, _ = _make_client(_ok([{"id": 1}]))
    with patch("app.ingestion.fpl_client.httpx.AsyncClient", return_value=mock_cm):
        result = await get_fixtures()
    assert result == [{"id": 1}]


async def test_get_gameweek_live_passes_correct_url():
    mock_cm, mock_client = _make_client(_ok({"elements": []}))
    with patch("app.ingestion.fpl_client.httpx.AsyncClient", return_value=mock_cm):
        await get_gameweek_live(gameweek=5)
    url = mock_client.get.call_args[0][0]
    assert "/event/5/live/" in url


async def test_get_entry_picks_passes_correct_url():
    mock_cm, mock_client = _make_client(_ok({"picks": []}))
    with patch("app.ingestion.fpl_client.httpx.AsyncClient", return_value=mock_cm):
        await get_entry_picks(entry_id=42, gameweek=3)
    url = mock_client.get.call_args[0][0]
    assert "/entry/42/event/3/picks/" in url


# --- Retry behaviour ---

async def test_retries_once_on_timeout_then_succeeds(no_sleep):
    mock_cm, mock_client = _make_client(
        httpx.TimeoutException("timed out"),
        _ok({"teams": []}),
    )
    with patch("app.ingestion.fpl_client.httpx.AsyncClient", return_value=mock_cm):
        result = await get_bootstrap_static()
    assert result == {"teams": []}
    assert mock_client.get.call_count == 2


async def test_retries_on_connect_error(no_sleep):
    mock_cm, mock_client = _make_client(
        httpx.ConnectError("connection refused"),
        _ok({"teams": []}),
    )
    with patch("app.ingestion.fpl_client.httpx.AsyncClient", return_value=mock_cm):
        result = await get_bootstrap_static()
    assert result == {"teams": []}
    assert mock_client.get.call_count == 2


async def test_retries_on_5xx_then_succeeds(no_sleep):
    mock_cm, mock_client = _make_client(
        _http_error(503),
        _ok({"teams": []}),
    )
    with patch("app.ingestion.fpl_client.httpx.AsyncClient", return_value=mock_cm):
        result = await get_bootstrap_static()
    assert result == {"teams": []}
    assert mock_client.get.call_count == 2


async def test_raises_after_three_failed_attempts(no_sleep):
    mock_cm, mock_client = _make_client(
        httpx.TimeoutException("t1"),
        httpx.TimeoutException("t2"),
        httpx.TimeoutException("t3"),
    )
    with patch("app.ingestion.fpl_client.httpx.AsyncClient", return_value=mock_cm):
        with pytest.raises(httpx.TimeoutException):
            await get_bootstrap_static()
    assert mock_client.get.call_count == 3


async def test_does_not_retry_4xx(no_sleep):
    """4xx errors are caller mistakes — retrying won't help."""
    mock_cm, mock_client = _make_client(_http_error(404))
    with patch("app.ingestion.fpl_client.httpx.AsyncClient", return_value=mock_cm):
        with pytest.raises(httpx.HTTPStatusError):
            await get_bootstrap_static()
    assert mock_client.get.call_count == 1
