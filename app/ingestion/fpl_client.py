import time
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from app.core.config import settings

# TTL cache keyed by URL. Entries are (fetched_at, data).
# bootstrap-static and fixtures change at most once per GW processing cycle;
# live data updates during active matches so gets a shorter window.
_CACHE: dict[str, tuple[float, object]] = {}
_TTL_SLOW = 300   # bootstrap-static, fixtures: 5 min
_TTL_LIVE  = 120  # gameweek live: 2 min


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500:
        return True
    return False


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
async def _get(url: str) -> dict | list:
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


async def _get_cached(url: str, ttl: float) -> dict | list:
    now = time.monotonic()
    entry = _CACHE.get(url)
    if entry is not None:
        fetched_at, data = entry
        if now - fetched_at < ttl:
            return data
    data = await _get(url)
    _CACHE[url] = (now, data)
    return data


async def get_bootstrap_static() -> dict:
    return await _get_cached(
        f"{settings.fpl_api_base_url}/bootstrap-static/", _TTL_SLOW
    )


async def get_fixtures() -> list[dict]:
    return await _get_cached(
        f"{settings.fpl_api_base_url}/fixtures/", _TTL_SLOW
    )


async def get_gameweek_live(gameweek: int) -> dict:
    return await _get_cached(
        f"{settings.fpl_api_base_url}/event/{gameweek}/live/", _TTL_LIVE
    )


async def get_entry_picks(entry_id: int, gameweek: int) -> dict:
    return await _get(f"{settings.fpl_api_base_url}/entry/{entry_id}/event/{gameweek}/picks/")


async def get_entry_history(entry_id: int) -> dict:
    return await _get(f"{settings.fpl_api_base_url}/entry/{entry_id}/history/")


async def get_entry_details(entry_id: int) -> dict:
    return await _get(f"{settings.fpl_api_base_url}/entry/{entry_id}/")


async def get_league_standings(league_id: int, page: int = 1) -> dict:
    return await _get_cached(
        f"{settings.fpl_api_base_url}/leagues-classic/{league_id}/standings/?page_standings={page}",
        _TTL_SLOW,
    )
