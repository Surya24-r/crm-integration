from psycopg.types.json import Jsonb

from app.db import execute, fetch_one


def log_call(
    deal_id: str | None,
    system: str,
    method: str,
    url: str,
    status_code: int | None,
    duration_ms: int,
    request_body,
    response_body,
    error: str | None,
) -> None:
    execute(
        """
        insert into integration_log
          (crm_deal_id, system, method, url, status_code, duration_ms,
           request_body, response_body, error)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            deal_id,
            system,
            method,
            url,
            status_code,
            duration_ms,
            Jsonb(request_body) if request_body is not None else None,
            Jsonb(response_body) if response_body is not None else None,
            error,
        ),
    )


def calls_for_deal(deal_id: str, system: str = "zoho") -> int:
    row = fetch_one(
        "select count(*) as n from integration_log where crm_deal_id = %s and system = %s",
        (deal_id, system),
    )
    return int(row["n"])