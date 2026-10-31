import threading
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings
from app.db import execute, fetch_one
from app.integration_log import log_call


# ---------- errors ----------
class ZohoError(Exception):
    def __init__(self, message, status=None, code=None, retryable=False, retry_after=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after


class ZohoRateLimited(ZohoError):
    """Per-minute limit hit: retry after a short wait."""


class ZohoDailyLimit(ZohoError):
    """Daily API quota used up: park jobs until the daily reset."""


# ---------- rate limiter (token bucket) ----------
class RateLimiter:
    def __init__(self, per_minute: int):
        self.capacity = float(per_minute)
        self.tokens = float(per_minute)
        self.rate = per_minute / 60.0
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            time.sleep(wait)


# ---------- OAuth token handling ----------
class TokenProvider:
    def __init__(self, http: httpx.Client):
        self.http = http
        self.lock = threading.Lock()
        self.token: str | None = None
        self.expires_at: float = 0.0  # epoch seconds

    def get(self, force: bool = False) -> str:
        with self.lock:
            if not force and self.token and time.time() < self.expires_at - 60:
                return self.token
            if not force:
                row = fetch_one("select access_token, expires_at from oauth_tokens where id = 1")
                if row and row["access_token"] and row["expires_at"]:
                    exp = row["expires_at"].timestamp()
                    if exp - 60 > time.time():
                        self.token, self.expires_at = row["access_token"], exp
                        return self.token
            return self._refresh()

    def _refresh(self) -> str:
        url = f"{settings.zoho_accounts_url}/oauth/v2/token"
        start = time.monotonic()
        try:
            r = self.http.post(
                url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": settings.zoho_refresh_token,
                    "client_id": settings.zoho_client_id,
                    "client_secret": settings.zoho_client_secret,
                },
            )
        except httpx.TransportError as e:
            log_call(None, "zoho", "POST", url, None, _ms(start), None, None, str(e))
            raise ZohoError(f"token refresh network error: {e}", retryable=True)

        body = _parse(r)
        # never log the token itself
        safe = {k: v for k, v in body.items() if k not in ("access_token", "refresh_token")}
        log_call(None, "zoho", "POST", url, r.status_code, _ms(start), None, safe,
                 None if "access_token" in body else str(body))

        if "access_token" not in body:
            err = str(body.get("error", body))
            # Zoho throttles refresh calls: treat that as temporary
            retryable = "too many requests" in err.lower()
            raise ZohoError(f"token refresh failed: {err}", status=r.status_code, retryable=retryable)

        self.token = body["access_token"]
        ttl = int(body.get("expires_in", 3600))
        self.expires_at = time.time() + ttl
        expires = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        execute(
            """
            insert into oauth_tokens (id, access_token, expires_at) values (1, %s, %s)
            on conflict (id) do update
              set access_token = excluded.access_token, expires_at = excluded.expires_at
            """,
            (self.token, expires),
        )
        return self.token


# ---------- helpers ----------
def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _parse(r: httpx.Response) -> dict:
    try:
        data = r.json()
        return data if isinstance(data, dict) else {"data": data}
    except Exception:
        return {"raw": r.text[:2000]}


# ---------- the client ----------
class ZohoClient:
    def __init__(self):
        self.http = httpx.Client(timeout=30)
        self.limiter = RateLimiter(settings.zoho_rate_per_minute)
        self.tokens = TokenProvider(self.http)

    def request(self, method: str, path: str, *, deal_id: str | None = None,
                params: dict | None = None, json_body: dict | None = None) -> dict:
        url = f"{settings.zoho_api_url}{path}"
        query = {"organization_id": settings.zoho_org_id, **(params or {})}
        force_refresh = False

        for attempt in range(2):
            self.limiter.acquire()
            token = self.tokens.get(force=force_refresh)
            start = time.monotonic()
            try:
                r = self.http.request(
                    method, url, params=query, json=json_body,
                    headers={"Authorization": f"Zoho-oauthtoken {token}"},
                )
            except httpx.TransportError as e:
                log_call(deal_id, "zoho", method, url, None, _ms(start), json_body, None, str(e))
                raise ZohoError(f"network error: {e}", retryable=True)

            body = _parse(r)
            failed = (not r.is_success) or body.get("code", 0) != 0
            log_call(deal_id, "zoho", method, url, r.status_code, _ms(start),
                     json_body, body, body.get("message") if failed else None)

            # expired/invalid token: refresh once and retry
            if r.status_code == 401 and attempt == 0:
                force_refresh = True
                continue
            return self._handle(r, body)

        raise ZohoError("unreachable")  # pragma: no cover

    def _handle(self, r: httpx.Response, body: dict) -> dict:
        status = r.status_code
        code = body.get("code")
        msg = str(body.get("message", body))

        if status == 429:
            text = msg.lower()
            if "per day" in text or "daily" in text:
                raise ZohoDailyLimit(msg, status=status, code=code, retryable=True)
            try:
                wait = int(r.headers.get("Retry-After", 60))
            except ValueError:
                wait = 60
            raise ZohoRateLimited(msg, status=status, code=code, retryable=True, retry_after=wait)
        if status >= 500:
            raise ZohoError(msg, status=status, code=code, retryable=True)
        if status >= 400:
            raise ZohoError(msg, status=status, code=code, retryable=False)
        if code not in (0, None):
            raise ZohoError(msg, status=status, code=code, retryable=False)
        return body

    # convenience wrappers
    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)

    def put(self, path, **kw):
        return self.request("PUT", path, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)