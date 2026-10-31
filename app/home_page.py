"""Home page: entry point for reviewers. Links to the deal, log and collections pages."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>CRM to Zoho Books integration</title>
<style>
body { font-family: system-ui, sans-serif; margin: 24px; color: #222; max-width: 820px; }
h2 { margin-bottom: 4px; }
ul { line-height: 1.7; }
.note { color: #555; font-size: 14px; }
</style></head>
<body>
<h2>CRM to Zoho Books integration</h2>
<p class="note">Pipedrive (CRM) to Zoho Books (accounting). A won deal creates a customer,
a sales order and three milestone invoices in Zoho Books. Payments and voids flow back to the deal.</p>

<h3>Pages</h3>
<ul>
  <li><a href="/deals/18/view">Deal page</a>: sync state, sales order, milestone invoices, payments, metrics, jobs, retry.
      Deal 18 shows an overdue invoice and a voided invoice. Deal 2 shows a full sales order and a payment.</li>
  <li><a href="/log">Integration log</a>: every Zoho Books and Pipedrive call, with the deal it belongs to.
      Filter by deal with <code>/log?deal=2</code>.</li>
  <li><a href="/collections">Collections</a>: outstanding amount per customer, aging buckets,
      oldest unpaid invoice and the deals it belongs to.</li>
</ul>

<h3>Other</h3>
<ul>
  <li><a href="/health">Health check</a></li>
  <li>Source code and README: see the GitHub repository.</li>
</ul>
</body></html>"""


@router.get("/", response_class=HTMLResponse)
def home():
    return PAGE