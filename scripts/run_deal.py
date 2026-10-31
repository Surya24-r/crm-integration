"""Runs the sync and processing steps for one deal directly, without the queue,
so any error prints in full. Run: python -m scripts.run_deal 2"""
import sys
import traceback

from app.db import close_pool, fetch_one, open_pool
from app.handlers import sync_then_process
from app.process_deal import handle_process_deal
from app.process_invoices import handle_process_invoices

deal_id = sys.argv[1]
open_pool()
job = {"crm_deal_id": deal_id, "id": 0, "type": "manual"}

for name, step in [("sync", lambda: sync_then_process(job)),
                   ("process", lambda: handle_process_deal(job)),
                   ("invoices", lambda: handle_process_invoices(job))]:
    try:
        step()
        print(f"{name}: ok")
    except Exception:
        print(f"{name}: FAILED")
        traceback.print_exc()
        break

row = fetch_one("select crm_status, state, needs_review, review_reason, last_error, "
                "zoho_customer_id, zoho_so_id from deals where crm_deal_id = %s", (deal_id,))
print("deal:", row)
close_pool()