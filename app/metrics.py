"""Deal-level numbers shown on the CRM deal. compute_metrics is pure (tested);
refresh_metrics reads the local mirror and writes only the fields that changed."""
from datetime import date

from app.crm_sync import write_owned
from app.db import execute, fetch_all, fetch_one
from app.deps import crm
from app.money import from_minor


def compute_metrics(so_total_minor: int, invoices: list[dict], today: date) -> dict:
    live = [i for i in invoices if i["status"] != "void"]
    invoiced = sum(i["total_minor"] for i in live)
    unpaid = sum(i["balance_minor"] for i in live)
    collected = invoiced - unpaid
    not_invoiced = so_total_minor - invoiced
    open_items = [i for i in live if i["balance_minor"] > 0 and i["due_date"]]
    next_due = min((i["due_date"] for i in open_items), default=None)
    overdue = any(i["due_date"] < today for i in open_items)

    def pct(part: int) -> float:
        return round(part * 100 / so_total_minor, 2) if so_total_minor else 0.0

    return {
        "so_total_minor": so_total_minor,
        "invoiced_minor": invoiced,
        "collected_minor": collected,
        "unpaid_minor": unpaid,
        "not_invoiced_minor": not_invoiced,
        "pct_invoiced": pct(invoiced),
        "pct_collected": pct(collected),
        "next_due_date": next_due.isoformat() if next_due else None,
        "overdue": overdue,
    }


def refresh_metrics(deal_id: str) -> dict:
    deal = fetch_one("select so_total_minor from deals where crm_deal_id = %s", (deal_id,))
    invoices = fetch_all(
        "select status, total_minor, balance_minor, due_date from invoices where crm_deal_id = %s",
        (deal_id,))
    m = compute_metrics(deal["so_total_minor"] or 0, invoices, date.today())
    execute("update deals set metrics = metrics || %s::jsonb, updated_at = now() where crm_deal_id = %s",
            (__import__("json").dumps(m, default=str), deal_id))

    d = crm.get(f"/deals/{deal_id}", deal_id=deal_id)["data"]
    write_owned(crm, d, {
        "Zoho % Invoiced": m["pct_invoiced"],
        "Zoho % Collected": m["pct_collected"],
        "Zoho Invoiced Unpaid": float(from_minor(m["unpaid_minor"])),
        "Zoho Not Yet Invoiced": float(from_minor(m["not_invoiced_minor"])),
        "Zoho Next Due Date": m["next_due_date"],
        "Zoho Overdue": "Yes" if m["overdue"] else "No",
    })
    return m