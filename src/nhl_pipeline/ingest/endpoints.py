"""NHL endpoint URLs and a polite HTTP fetcher.

All network access in the pipeline goes through Fetcher, so the pacing,
retries and User-Agent live in one place. The NHL services are unofficial and
undocumented: if an endpoint changes, this is the module that should need to
change.
"""

import time

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

WEB_BASE = "https://api-web.nhle.com/v1"
STATS_BASE = "https://api.nhle.com/stats/rest/en"
USER_AGENT = "nhl-analytics-portfolio/0.1 (personal project)"
MIN_INTERVAL_SECONDS = 1.0  # minimum gap between the starts of two requests


class RetryableHTTPError(Exception):
    """Server-side or rate-limit error worth retrying."""


def schedule_url(date):
    """League schedule for the week starting at `date` (YYYY-MM-DD)."""
    return f"{WEB_BASE}/schedule/{date}"


def game_requests(game_id):
    """The three calls that make up one game, as (name, url, params)."""
    return [
        ("play-by-play", f"{WEB_BASE}/gamecenter/{game_id}/play-by-play", None),
        ("boxscore", f"{WEB_BASE}/gamecenter/{game_id}/boxscore", None),
        (
            "shiftcharts",
            f"{STATS_BASE}/shiftcharts",
            {"cayenneExp": f"gameId={game_id}"},
        ),
    ]


def _new_session():
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


class Fetcher:
    """GET requests spaced at least `min_interval` seconds apart.

    Server errors (5xx), rate limits (429), timeouts and connection errors are
    retried with backoff. Anything else, including 404, is returned to the
    caller, who decides what it means.
    """

    def __init__(
        self,
        min_interval=MIN_INTERVAL_SECONDS,
        session=None,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        self.min_interval = min_interval
        self.session = session or _new_session()
        self._clock = clock
        self._sleep = sleep
        self._last_start = None

    def _wait_turn(self):
        if self._last_start is not None:
            remaining = self.min_interval - (self._clock() - self._last_start)
            if remaining > 0:
                self._sleep(remaining)
        self._last_start = self._clock()

    @retry(
        retry=retry_if_exception_type(
            (requests.ConnectionError, requests.Timeout, RetryableHTTPError)
        ),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def get(self, url, params=None):
        self._wait_turn()
        response = self.session.get(url, params=params, timeout=30)
        if response.status_code >= 500 or response.status_code == 429:
            raise RetryableHTTPError(f"{response.status_code} from {url}")
        return response