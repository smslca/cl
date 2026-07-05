"""Shared NSE HTTP client: cookie warmup, retries, and bhavcopy download."""

import datetime
import io
import time

import pandas as pd
import requests

BROWSER_HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
    ),
}

BHAVCOPY_URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"


class NotFound(Exception):
    """Resource does not exist (holiday / not yet published). Not retryable."""


class NSEClient:
    def __init__(self, retries: int = 3, backoff: float = 2.0):
        self.retries = retries
        self.backoff = backoff
        self._session = None

    def _new_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update(BROWSER_HEADERS)
        # www.nseindia.com APIs require cookies set by the homepage
        s.get("https://www.nseindia.com", timeout=30)
        return s

    def get(self, url: str) -> requests.Response:
        last_err = None
        for attempt in range(self.retries):
            try:
                if self._session is None:
                    self._session = self._new_session()
                resp = self._session.get(url, timeout=30)
                if resp.status_code == 404:
                    raise NotFound(url)
                if resp.status_code in (401, 403):
                    # stale/blocked cookies: force a fresh session on retry
                    self._session = None
                    resp.raise_for_status()
                resp.raise_for_status()
                return resp
            except NotFound:
                raise
            except Exception as e:  # noqa: BLE001 - retry any transport error
                last_err = e
                time.sleep(self.backoff * (attempt + 1))
        raise RuntimeError(f"NSE request failed after {self.retries} attempts: {url}") from last_err

    def get_json(self, url: str):
        return self.get(url).json()


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """NSE archive CSVs pad columns and values with spaces; strip them."""
    df.columns = [c.strip() for c in df.columns]
    for col in df.select_dtypes(include="object"):
        df[col] = df[col].str.strip()
    return df


def fetch_bhavcopy(client: NSEClient, date: datetime.date) -> pd.DataFrame:
    """Full bhavcopy with delivery data for one trading day. Raises NotFound on holidays."""
    url = BHAVCOPY_URL.format(ddmmyyyy=date.strftime("%d%m%Y"))
    resp = client.get(url)
    df = normalize(pd.read_csv(io.StringIO(resp.text)))
    # On some holidays the archive serves the previous day's file instead of a
    # 404 — verify the content is actually for the date we asked for.
    if df["DATE1"].iloc[0] != date.strftime("%d-%b-%Y"):
        raise NotFound(f"{url} returned data for {df['DATE1'].iloc[0]}, not {date}")
    return df


def write_snapshot(df: pd.DataFrame, path, min_rows: int) -> None:
    """Write a raw daily snapshot, refusing suspiciously small payloads."""
    if len(df) < min_rows:
        raise RuntimeError(f"refusing to write {path}: only {len(df)} rows (expected >= {min_rows})")
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
