"""Pulls the current state of every invoice we know about from Zoho Books and
updates the local mirror. Also catches voids, deletions and payments recorded
directly in Zoho. Idempotent: running it twice changes nothing the second time."""
from datetime import date

from app import zoho_books
from app.db import execute, fetch_all, fetch_one
from app.deps import crm, zoho
from app.metrics import refresh_metrics
from app.money import to_minor
from app.process_deal import _review


def _void_local(zoho_invoice_id: str, deal_id: str) -> None:
    execute(
        """update invoices set status = 'void', voided_at = coalesce(voided_at, now()), synced_at = now()
           where zoho_invoice_id = %s""", (zoho_invoice_id,))


def _sync_payments(deal_id: str, zoho_invoice_id: str) -> None:
    """Mirror payments applied to one invoice. The list view does not include the
    per-invoice breakdown, so for candidate payments we fetch the full record."""
    deal = fetch_one("select zoho_customer_id, org_name from deals where crm_deal_id = %s", (deal_id,))
    inv = fetch_one("select invoice_number from invoices where zoho_invoice_id = %s", (zoho_invoice_id,))
    if not deal or not deal["zoho_customer_id"] or not inv:
        return
    page = 1
    while True:
        data = zoho.get("/customerpayments", deal_id=deal_id,
                        params={"customer_id": deal["zoho_customer_id"],
                                "per_page": 200, "page": page})
        for summary in data.get("customerpayments") or []:
            # cheap pre-filter: only payments whose list entry mentions this invoice
            if inv["invoice_number"] not in (summary.get("invoice_numbers") or ""):
                continue
            full = zoho.get(f"/customerpayments/{summary['payment_id']}", deal_id=deal_id)["payment"]
            for applied in full.get("invoices") or []:
                if applied.get("invoice_id") != zoho_invoice_id:
                    continue
                execute(
                    """insert into payments (zoho_payment_id, zoho_invoice_id, crm_deal_id,
                                             amount_minor, paid_on, zoho_modified_at)
                       values (%s, %s, %s, %s, %s, %s)
                       on conflict (zoho_payment_id, zoho_invoice_id) do update set
                         amount_minor = excluded.amount_minor, paid_on = excluded.paid_on,
                         zoho_modified_at = excluded.zoho_modified_at""",
                    (full["payment_id"], zoho_invoice_id, deal_id,
                     to_minor(applied["amount_applied"]), full.get("date") or None,
                     full.get("last_modified_time") or None),
                )
        if not (data.get("page_context") or {}).get("has_more_page"):
            break
        page += 1

def reconcile_invoice(deal_id: str, zoho_invoice_id: str) -> None:
    inv = zoho.get(f"/invoices/{zoho_invoice_id}", deal_id=deal_id).get("invoice")
    if inv is None or inv.get("status") == "void":
        _void_local(zoho_invoice_id, deal_id)
        return
    zoho_books_mirror = zoho_books  # keeps the import used for clarity
    from app.process_invoices import mirror_invoice
    mirror_invoice(deal_id, None, inv)
    _sync_payments(deal_id, zoho_invoice_id)


def reconcile_deal(deal_id: str) -> None:
    """Refresh every invoice of one deal, then recompute its metrics and write them back."""
    rows = fetch_all("select zoho_invoice_id from invoices where crm_deal_id = %s", (deal_id,))
    for r in rows:
        try:
            reconcile_invoice(deal_id, r["zoho_invoice_id"])
        except Exception as e:
            if "not found" in str(e).lower() or "invalid" in str(e).lower():
                _void_local(r["zoho_invoice_id"], deal_id)
            else:
                raise
    refresh_metrics(deal_id)


def reconcile_all(limit: int = 200) -> int:
    rows = fetch_all(
        """select distinct crm_deal_id from invoices
           where crm_deal_id is not null and status is distinct from 'void'
           order by crm_deal_id limit %s""", (limit,))
    for r in rows:
        reconcile_deal(r["crm_deal_id"])
    return len(rows)