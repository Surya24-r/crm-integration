"""Collections view data: outstanding amounts per customer with aging buckets.
Aging is measured from the due date. Reads only our local mirror."""
from datetime import date

from app.db import fetch_all

BUCKETS = ["current", "1_30", "31_60", "61_90", "90_plus"]


def bucket_for(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "current"
    if days_overdue <= 30:
        return "1_30"
    if days_overdue <= 60:
        return "31_60"
    if days_overdue <= 90:
        return "61_90"
    return "90_plus"


def collections(today: date) -> list[dict]:
    rows = fetch_all(
        """select d.org_name, i.crm_deal_id, i.zoho_invoice_id, i.invoice_number,
                  i.balance_minor, i.due_date
           from invoices i join deals d on d.crm_deal_id = i.crm_deal_id
           where i.status is distinct from 'void' and i.balance_minor > 0""")
    by_customer: dict[str, dict] = {}
    for r in rows:
        c = by_customer.setdefault(r["org_name"], {
            "customer": r["org_name"], "outstanding_minor": 0,
            "buckets": {b: 0 for b in BUCKETS}, "oldest_date": None,
            "oldest_invoice": None, "deals": set(),
        })
        c["outstanding_minor"] += r["balance_minor"]
        c["deals"].add(r["crm_deal_id"])
        due = r["due_date"]
        days = (today - due).days if due else 0
        c["buckets"][bucket_for(days)] += r["balance_minor"]
        if due and (c["oldest_date"] is None or due < c["oldest_date"]):
            c["oldest_date"] = due
            c["oldest_invoice"] = r["invoice_number"]
    out = []
    for c in by_customer.values():
        out.append({
            "customer": c["customer"],
            "outstanding_minor": c["outstanding_minor"],
            "buckets": c["buckets"],
            "oldest": ({"invoice": c["oldest_invoice"], "due_date": c["oldest_date"].isoformat()}
                       if c["oldest_date"] else None),
            "deals": sorted(c["deals"]),
        })
    return sorted(out, key=lambda x: -x["outstanding_minor"])