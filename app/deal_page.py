"""Deal page: one deal's sync state, sales order, milestones, invoices, payments,
metrics, and a retry button. Served at /deals/{id}/view. Read-only except retry,
which posts to the existing retry endpoint with the admin key typed by the user
(the key is never stored in the HTML)."""
import html
import json

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.config import settings
from app.db import fetch_all, fetch_one

router = APIRouter()

CSS = """
body { font-family: system-ui, sans-serif; margin: 24px; color: #222; max-width: 1100px; }
h2 { margin-bottom: 4px; } h3 { margin-top: 28px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; margin-top: 8px; }
th, td { border-bottom: 1px solid #eee; padding: 6px 8px; text-align: left; }
th { background: #f5f5f5; }
.kv td:first-child { width: 220px; color: #555; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; background: #eef; }
.bad { color: #b00020; } .ok { color: #137333; }
.alert { background: #fff4f4; border: 1px solid #f0b4b4; padding: 10px; border-radius: 6px; }
.note { background: #f7f9fc; border: 1px solid #dde4ee; padding: 10px; border-radius: 6px; font-size: 13px; }
input[type=password] { padding: 4px; width: 220px; }
button { padding: 6px 12px; }
"""


def _money(minor) -> str:
    if minor is None:
        return "-"
    return f"AED {minor / 100:,.2f}"


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


@router.get("/deals/{deal_id}/view", response_class=HTMLResponse)
def deal_view(deal_id: str):
    deal = fetch_one("select * from deals where crm_deal_id = %s", (deal_id,))
    if not deal:
        return HTMLResponse(f"<h3>No deal {_e(deal_id)} in the local database.</h3>", status_code=404)

    milestones = fetch_all(
        """select m.seq, m.label, m.pct_bp, m.amount_minor, m.net_minor, m.due_date,
                  m.reached_at, m.zoho_invoice_id, i.invoice_number, i.status, i.balance_minor
           from milestones m left join invoices i on i.zoho_invoice_id = m.zoho_invoice_id
           where m.crm_deal_id = %s order by m.seq""", (deal_id,))
    payments = fetch_all(
        """select p.zoho_payment_id, p.amount_minor, p.paid_on, i.invoice_number
           from payments p left join invoices i on i.zoho_invoice_id = p.zoho_invoice_id
           where p.crm_deal_id = %s order by p.paid_on, p.zoho_payment_id""", (deal_id,))
    jobs = fetch_all(
        """select id, type, status, attempts, last_error, updated_at
           from jobs where crm_deal_id = %s order by id desc limit 10""", (deal_id,))

    m = deal["metrics"] or {}
    so_link = None
    if deal["zoho_so_id"]:
        so_link = f"{settings.zoho_app_url}/{settings.zoho_org_id}#/salesorders/{deal['zoho_so_id']}"

    alert = ""
    if deal["needs_review"]:
        alert = f"<div class='alert'><b>Needs review:</b> {_e(deal['review_reason'])}</div>"
    elif deal["last_error"]:
        alert = f"<div class='alert'><b>Last error:</b> {_e(deal['last_error'])}</div>"

    milestone_rows = "".join(
        "<tr>"
        f"<td>{r['seq']}</td><td>{_e(r['label'])}</td><td>{r['pct_bp'] / 100:.0f}%</td>"
        f"<td>{_money(r['amount_minor'])}</td><td>{_money(r['net_minor'])}</td>"
        f"<td>{_e(r['due_date'])}</td>"
        f"<td>{_e(r['invoice_number'] or 'not raised')}</td>"
        f"<td>{_e(r['status'] or '-')}</td>"
        f"<td>{_money(r['balance_minor']) if r['zoho_invoice_id'] and r['status'] != 'void' else '-'}</td>"        "</tr>"
        for r in milestones
    ) or "<tr><td colspan='9'>No milestones yet.</td></tr>"

    payment_rows = "".join(
        "<tr>"
        f"<td>{_e(r['paid_on'])}</td><td>{_e(r['invoice_number'])}</td>"
        f"<td>{_money(r['amount_minor'])}</td><td>{_e(r['zoho_payment_id'])}</td>"
        "</tr>"
        for r in payments
    ) or "<tr><td colspan='4'>No payments recorded.</td></tr>"

    job_rows = "".join(
        "<tr>"
        f"<td>{j['id']}</td><td>{_e(j['type'])}</td><td>{_e(j['status'])}</td>"
        f"<td>{j['attempts']}</td><td>{_e(j['last_error'] or '')}</td>"
        "</tr>"
        for j in jobs
    ) or "<tr><td colspan='5'>No jobs.</td></tr>"

    so_cell = (f"<a href='{_e(so_link)}' target='_blank'>{_e(deal['zoho_so_id'])}</a>"
               if so_link else "not created")

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Deal {_e(deal_id)}</title>
<style>{CSS}</style></head>
<body>
<h2>{_e(deal['title'])} <span class='badge'>{_e(deal['state'])}</span></h2>
<div>{_e(deal['org_name'])} &middot; CRM deal {_e(deal_id)} &middot; CRM status: {_e(deal['crm_status'])}</div>
{alert}

<h3>Sync</h3>
<table class='kv'>
<tr><td>Sales order</td><td>{so_cell}</td></tr>
<tr><td>Zoho customer id</td><td>{_e(deal['zoho_customer_id'] or 'not created')}</td></tr>
<tr><td>Deal value (net)</td><td>{_money(deal['net_amount_minor'])}</td></tr>
<tr><td>Sales order total (incl. VAT)</td><td>{_money(deal['so_total_minor'])}</td></tr>
<tr><td>Go-live date</td><td>{_e(deal['go_live_date'] or 'not set')}</td></tr>
</table>

<h3>Metrics</h3>
<table class='kv'>
<tr><td>% invoiced</td><td>{_e(m.get('pct_invoiced', '-'))}</td></tr>
<tr><td>% collected</td><td>{_e(m.get('pct_collected', '-'))} (payments received &divide; sales order total)</td></tr>
<tr><td>Invoiced but unpaid</td><td>{_money(m.get('unpaid_minor'))}</td></tr>
<tr><td>Not yet invoiced</td><td>{_money(m.get('not_invoiced_minor'))}</td></tr>
<tr><td>Next due date</td><td>{_e(m.get('next_due_date') or '-')}</td></tr>
<tr><td>Overdue</td><td class='{'bad' if m.get('overdue') else 'ok'}'>{'Yes' if m.get('overdue') else 'No'}</td></tr>
</table>

<h3>Milestones</h3>
<table>
<tr><th>#</th><th>Label</th><th>Share</th><th>Gross (incl. VAT)</th><th>Net</th>
<th>Due</th><th>Invoice</th><th>Status</th><th>Balance</th></tr>
{milestone_rows}
</table>

<h3>Payments</h3>
<table>
<tr><th>Paid on</th><th>Invoice</th><th>Amount</th><th>Zoho payment id</th></tr>
{payment_rows}
</table>

<h3>Recent jobs</h3>
<table>
<tr><th>Id</th><th>Type</th><th>Status</th><th>Attempts</th><th>Last error</th></tr>
{job_rows}
</table>

<h3>Retry</h3>
<div class='note'>
Use this after fixing the cause of a failure (for example, a product mapping or a
Zoho setting). It re-queues the deal's failed or retrying jobs. Each step checks for
existing Zoho records first, so retrying never creates duplicates.
<form onsubmit="return retryDeal(event)" style="margin-top:10px">
  Admin key: <input type="password" id="adminKey" autocomplete="off">
  <button type="submit">Retry this deal</button>
  <span id="retryResult"></span>
</form>
</div>

<script>
async function retryDeal(ev) {{
  ev.preventDefault();
  const key = document.getElementById('adminKey').value;
  const out = document.getElementById('retryResult');
  out.textContent = 'sending...';
  try {{
    const r = await fetch('/deals/{_e(deal_id)}/retry', {{
      method: 'POST', headers: {{ 'x-admin-key': key }}
    }});
    const body = await r.text();
    out.textContent = r.ok ? 'requeued' : ('failed: ' + r.status + ' ' + body);
  }} catch (e) {{
    out.textContent = 'network error: ' + e;
  }}
  return false;
}}
</script>
</body></html>"""