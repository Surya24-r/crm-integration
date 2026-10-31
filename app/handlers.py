from app.db import fetch_one
from app.jobs import enqueue
from app.process_deal import handle_process_deal
from app.process_invoices import handle_process_invoices
from app.sync_deal import handle_sync_deal


def sync_then_process(job: dict) -> None:
    """Load the deal from the CRM; if it is won, queue the Zoho work as its own job."""
    handle_sync_deal(job)
    deal_id = job["crm_deal_id"]
    row = fetch_one("select crm_status from deals where crm_deal_id = %s", (deal_id,))
    if row and row["crm_status"] == "won":
        enqueue("process_deal", deal_id, f"process_deal:{deal_id}")


def process_then_invoice(job: dict) -> None:
    handle_process_deal(job)
    enqueue("process_invoices", job["crm_deal_id"], f"process_invoices:{job['crm_deal_id']}")


HANDLERS = {
    "sync_deal": sync_then_process,
    "process_deal": process_then_invoice,
    "process_invoices": handle_process_invoices,
}