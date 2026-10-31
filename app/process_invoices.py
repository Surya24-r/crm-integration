"""Raises milestone invoices in Zoho Books and records payments.
Every step looks for an existing record first, so a crash or a repeat never duplicates."""
from datetime import date

from app import zoho_books
from app.config import settings
from app.db import execute, fetch_all, fetch_one
from app.deps import zoho
from app.errors import DataError
from app.jobs import enqueue
from app.metrics import refresh_metrics
from app.money import to_minor
from app.process_deal import _review
from app.schedule import due_milestones


def _deal_url(deal_id: str) -> str:
    return f"{settings.crm_base_url.split('/api/')[0]}/deal/{deal_id}"


def mirror_invoice(deal_id: str, seq: int | None, inv: dict) -> None:
    """Keep the local copy of a Zoho invoice up to date."""
    execute(
        """insert into invoices (zoho_invoice_id, crm_deal_id, milestone_seq, invoice_number, status,
                                 total_minor, balance_minor, due_date, zoho_modified_at)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
           on conflict (zoho_invoice_id) do update set
             invoice_number = excluded.invoice_number, status = excluded.status,
             total_minor = excluded.total_minor, balance_minor = excluded.balance_minor,
             due_date = excluded.due_date, zoho_modified_at = excluded.zoho_modified_at,
             synced_at = now()""",
        (inv["invoice_id"], deal_id, seq, inv.get("invoice_number"), inv.get("status"),
         to_minor(inv["total"]), to_minor(inv.get("balance", inv["total"])),
         inv.get("due_date") or None, inv.get("last_modified_time") or None),
    )


def _item_for_deal(deal_id: str) -> str:
    row = fetch_one(
        """select m.zoho_item_id from deal_products p
           join product_item_map m on m.crm_product = p.crm_product
           where p.crm_deal_id = %s order by p.id limit 1""", (deal_id,))
    if not row:
        raise DataError("No mapped Zoho item for this deal's products. Check product_item_map.")
    return row["zoho_item_id"]


def handle_process_invoices(job: dict) -> None:
    deal_id = job["crm_deal_id"]
    deal = fetch_one("select * from deals where crm_deal_id = %s", (deal_id,))
    if (not deal or deal["needs_review"] or deal["crm_status"] != "won"
            or not deal["zoho_so_id"] or not deal["zoho_customer_id"]):
        return

    ensure_invoices_sent(deal_id) 
    milestones = fetch_all("select * from milestones where crm_deal_id = %s order by seq", (deal_id,))
    pending = due_milestones(milestones, date.today())
    if not pending:
        return

    item_id = _item_for_deal(deal_id)
    for m in pending:  # one at a time, in order
        reference = f"CRM-DEAL-{deal_id}-M{m['seq']}"
        inv = (zoho_books.find_invoice(zoho, reference, deal_id)
               or zoho_books.create_invoice(
                   zoho, deal, deal["zoho_customer_id"], deal["zoho_so_id"], m["seq"], m["label"],
                   m["net_minor"], m["due_date"] or date.today(), item_id, reference, _deal_url(deal_id)))

        # read the full invoice so the status and totals are current
        inv = zoho_books.get_invoice(zoho, inv["invoice_id"], deal_id)
        

        if to_minor(inv["total"]) != m["amount_minor"]:
            _review(deal_id, f"Invoice for milestone {m['seq']} totals {inv['total']} but the expected "
                             f"amount is {m['amount_minor'] / 100:.2f}. Check tax settings, then retry.")
            return

        if inv.get("status") == "draft":
            zoho.post(f"/invoices/{inv['invoice_id']}/status/sent", deal_id=deal_id)
            inv = zoho_books.get_invoice(zoho, inv["invoice_id"], deal_id)
        

        execute("update milestones set zoho_invoice_id = %s where crm_deal_id = %s and seq = %s",
                (inv["invoice_id"], deal_id, m["seq"]))
        mirror_invoice(deal_id, m["seq"], inv)
        execute("update deals set state = 'INVOICING', updated_at = now() where crm_deal_id = %s",
                (deal_id,))

    refresh_metrics(deal_id)

def record_payment(deal_id: str, seq: int, amount_minor: int, payment_key: str) -> dict:
    """Records a payment against one milestone invoice. Used by the admin endpoint
    (for testing and the seed script). In real use, Finance records payments in Zoho Books
    and the sync step picks them up."""
    if amount_minor <= 0:
        raise DataError("Payment amount must be greater than zero.")
    deal = fetch_one("select * from deals where crm_deal_id = %s", (deal_id,))
    m = fetch_one("select * from milestones where crm_deal_id = %s and seq = %s", (deal_id, seq))
    if not deal or not m or not m["zoho_invoice_id"]:
        raise DataError("That milestone has not been invoiced yet.")

    pay = (zoho_books.find_payment(zoho, payment_key, deal_id)
           or zoho_books.create_payment(zoho, deal_id, deal["zoho_customer_id"],
                                        m["zoho_invoice_id"], amount_minor, payment_key))
    execute(
        """insert into payments (zoho_payment_id, zoho_invoice_id, crm_deal_id, amount_minor, paid_on)
           values (%s, %s, %s, %s, current_date)
           on conflict (zoho_payment_id, zoho_invoice_id) do nothing""",
        (pay["payment_id"], m["zoho_invoice_id"], deal_id, amount_minor),
    )
    inv = zoho_books.get_invoice(zoho, m["zoho_invoice_id"], deal_id)
    mirror_invoice(deal_id, seq, inv)
    refresh_metrics(deal_id)
    return pay


def schedule_due_invoices() -> int:
    """Called by the poll loop: queues invoicing for any deal with a milestone now due."""
    rows = fetch_all(
        """select distinct m.crm_deal_id from milestones m
           join deals d on d.crm_deal_id = m.crm_deal_id
           where m.zoho_invoice_id is null and m.due_date <= current_date
             and d.zoho_so_id is not null and d.needs_review = false and d.crm_status = 'won'""")
    for r in rows:
        enqueue("process_invoices", r["crm_deal_id"], f"process_invoices:{r['crm_deal_id']}")
    return len(rows)

def ensure_invoices_sent(deal_id: str) -> None:
    """Moves any invoice of this deal still in draft to sent. Safe to repeat."""
    rows = fetch_all(
        "select zoho_invoice_id from milestones where crm_deal_id = %s and zoho_invoice_id is not null",
        (deal_id,))
    for r in rows:
        inv = zoho_books.get_invoice(zoho, r["zoho_invoice_id"], deal_id)
        
        if inv.get("status") == "draft":
            zoho.post(f"/invoices/{inv['invoice_id']}/status/sent", deal_id=deal_id)
            mirror_invoice(deal_id, None, zoho_books.get_invoice(zoho, inv["invoice_id"], deal_id))