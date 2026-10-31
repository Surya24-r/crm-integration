"""Integration log page: every Zoho Books and CRM call, filterable by deal.
Served at /log (all calls) and /log?deal=2 (one deal). Read-only."""
import html

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from app.db import fetch_all

router = APIRouter()

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Integration log</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 24px; color: #222; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ border-bottom: 1px solid #ddd; padding: 6px 8px; text-align: left; vertical-align: top; }}
th {{ background: #f4f4f4; position: sticky; top: 0; }}
.ok {{ color: #137333; }} .bad {{ color: #b00020; }}
code {{ font-size: 12px; word-break: break-all; }}
form {{ margin-bottom: 16px; }}
</style></head>
<body>
<h2>Integration log</h2>
<form method="get">
  Deal ID: <input name="deal" value="{deal}" size="10">
  Limit: <input name="limit" value="{limit}" size="5">
  <button type="submit">Filter</button>
  <a href="/log">Show all</a>
</form>
<p>{summary}</p>
<table>
<tr><th>Time</th><th>Deal</th><th>System</th><th>Method</th><th>URL</th>
<th>Status</th><th>ms</th><th>Error</th></tr>
{rows}
</table>
</body></html>"""


@router.get("/log", response_class=HTMLResponse)
def integration_log(deal: str | None = Query(None), limit: int = Query(200, ge=1, le=1000)):
    if deal:
        rows = fetch_all(
            """select at, crm_deal_id, system, method, url, status_code, duration_ms, error
               from integration_log where crm_deal_id = %s order by at desc, id desc limit %s""",
            (deal, limit))
        counts = fetch_all(
            "select system, count(*) as n from integration_log where crm_deal_id = %s group by system",
            (deal,))
    else:
        rows = fetch_all(
            """select at, crm_deal_id, system, method, url, status_code, duration_ms, error
               from integration_log order by at desc, id desc limit %s""", (limit,))
        counts = fetch_all("select system, count(*) as n from integration_log group by system")

    summary = " | ".join(f"{c['system']}: {c['n']} calls" for c in counts) or "No calls logged yet."
    body = []
    for r in rows:
        ok = r["error"] is None and (r["status_code"] or 0) < 400
        cls = "ok" if ok else "bad"
        status = r["status_code"] if r["status_code"] is not None else "network"
        body.append(
            "<tr>"
            f"<td>{r['at']:%Y-%m-%d %H:%M:%S}</td>"
            f"<td>{html.escape(str(r['crm_deal_id'] or '-'))}</td>"
            f"<td>{html.escape(r['system'])}</td>"
            f"<td>{html.escape(r['method'])}</td>"
            f"<td><code>{html.escape(r['url'])}</code></td>"
            f"<td class='{cls}'>{status}</td>"
            f"<td>{r['duration_ms'] or ''}</td>"
            f"<td>{html.escape(r['error'] or '')}</td>"
            "</tr>"
        )
    return PAGE.format(
        deal=html.escape(deal or ""), limit=limit, summary=html.escape(summary),
        rows="\n".join(body) or "<tr><td colspan='8'>No calls.</td></tr>",
    )