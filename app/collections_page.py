"""Collections page: per-customer outstanding amounts, aging buckets, oldest unpaid
invoice and the deals it belongs to. Served at /collections. Read-only."""
import html
from datetime import date

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.collections import BUCKETS, collections
from app.money import from_minor

router = APIRouter()

CSS = """
body { font-family: system-ui, sans-serif; margin: 24px; color: #222; }
table { border-collapse: collapse; width: 100%; font-size: 13px; margin-top: 12px; }
th, td { border-bottom: 1px solid #eee; padding: 6px 8px; text-align: left; vertical-align: top; }
th { background: #f5f5f5; }
td.num, th.num { text-align: right; white-space: nowrap; }
.overdue { color: #b00020; font-weight: 600; }
.note { color: #555; font-size: 13px; margin-top: 8px; }
"""

BUCKET_LABELS = {
    "current": "Current",
    "1_30": "1–30 days",
    "31_60": "31–60 days",
    "61_90": "61–90 days",
    "90_plus": "90+ days",
}


def _aed(minor: int) -> str:
    return f"{from_minor(minor):,.2f}"


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


@router.get("/collections", response_class=HTMLResponse)
def collections_page():
    today = date.today()
    rows = collections(today)

    totals = {b: 0 for b in BUCKETS}
    outstanding_total = 0
    for c in rows:
        outstanding_total += c["outstanding_minor"]
        for b in BUCKETS:
            totals[b] += c["buckets"][b]

    header_cells = "".join(f"<th class='num'>{BUCKET_LABELS[b]}</th>" for b in BUCKETS)

    body = []
    for c in rows:
        oldest = c["oldest"]
        oldest_cell = (f"{_e(oldest['invoice'])} (due {_e(oldest['due_date'])})"
                       if oldest else "-")
        bucket_cells = "".join(
            f"<td class='num{' overdue' if b != 'current' and c['buckets'][b] else ''}'>"
            f"{_aed(c['buckets'][b]) if c['buckets'][b] else '-'}</td>"
            for b in BUCKETS
        )
        body.append(
            "<tr>"
            f"<td>{_e(c['customer'])}</td>"
            f"<td class='num'>{_aed(c['outstanding_minor'])}</td>"
            f"{bucket_cells}"
            f"<td>{oldest_cell}</td>"
            f"<td>{_e(', '.join(c['deals']))}</td>"
            "</tr>"
        )

    total_cells = "".join(
        f"<td class='num'><b>{_aed(totals[b]) if totals[b] else '-'}</b></td>" for b in BUCKETS
    )
    total_row = (
        "<tr>"
        "<td><b>Total</b></td>"
        f"<td class='num'><b>{_aed(outstanding_total)}</b></td>"
        f"{total_cells}"
        "<td></td><td></td>"
        "</tr>"
    )

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Collections</title>
<style>{CSS}</style></head>
<body>
<h2>Collections</h2>
<div>As of {today.isoformat()} &middot; AED &middot; {len(rows)} customer(s) with an outstanding balance</div>
<table>
<tr><th>Customer</th><th class='num'>Outstanding</th>{header_cells}
<th>Oldest unpaid invoice</th><th>Deals</th></tr>
{''.join(body) or "<tr><td colspan='9'>Nothing outstanding.</td></tr>"}
{total_row if rows else ''}
</table>
<div class='note'>Aging is measured from the due date. Voided invoices and fully paid invoices are excluded.</div>
</body></html>"""