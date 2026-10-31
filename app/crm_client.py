import time

import httpx

from app.config import settings
from app.integration_log import log_call


class CrmError(Exception):
    def __init__(self, message, status=None, retryable=False, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _parse(r: httpx.Response) -> dict:
    try:
        data = r.json()
        return data if isinstance(data, dict) else {"data": data}
    except Exception:
        return {"raw": r.text[:2000]}


class CrmClient:
    def __init__(self):
        self.http = httpx.Client(timeout=30)
        self._field_keys: dict[str, str] | None = None

    def request(self, method: str, path: str, *, deal_id: str | None = None,
                params: dict | None = None, json_body: dict | None = None) -> dict:
        url = f"{settings.crm_base_url}{path}"
        start = time.monotonic()
        try:
            # token goes in a header so it never appears in the logged URL
            r = self.http.request(
                method, url, params=params, json=json_body,
                headers={"x-api-token": settings.crm_api_token},
            )
        except httpx.TransportError as e:
            log_call(deal_id, "crm", method, url, None, _ms(start), json_body, None, str(e))
            raise CrmError(f"network error: {e}", retryable=True)

        body = _parse(r)
        failed = (not r.is_success) or body.get("success") is False
        log_call(deal_id, "crm", method, url, r.status_code, _ms(start),
                 json_body, body, str(body.get("error", "")) if failed else None)

        if r.status_code == 429:
            try:
                wait = int(r.headers.get("Retry-After", 10))
            except ValueError:
                wait = 10
            raise CrmError("CRM rate limited", status=429, retryable=True, retry_after=wait)
        if r.status_code >= 500:
            raise CrmError(f"CRM server error {r.status_code}", status=r.status_code, retryable=True)
        if failed:
            raise CrmError(str(body.get("error", body)), status=r.status_code, retryable=False)
        return body

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)

    def put(self, path, **kw):
        return self.request("PUT", path, **kw)

    # ---- custom field keys (Pipedrive names them with hashes) ----
    def field_keys(self, refresh: bool = False) -> dict[str, str]:
        if self._field_keys is None or refresh:
            data = self.get("/dealFields", params={"limit": 500}).get("data") or []
            self._field_keys = {f["name"]: f["key"] for f in data}
        return self._field_keys

    def field_key(self, name: str) -> str:
        try:
            return self.field_keys()[name]
        except KeyError:
            raise CrmError(f"Custom field '{name}' not found. Run scripts.setup_crm_fields",
                           retryable=False)