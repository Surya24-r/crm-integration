"""Safety net: catches deals whose webhook was missed."""
from app.db import fetch_all
from app.deps import crm
from app.jobs import enqueue


def poll_once(limit: int = 100) -> int:
    rows = crm.get("/deals", params={
        "status": "all_not_deleted", "sort": "update_time DESC", "limit": limit,
    }).get("data") or []
    known = {r["crm_deal_id"]: r["crm_update_time"]
             for r in fetch_all("select crm_deal_id, crm_update_time from deals")}
    queued = 0
    for d in rows:
        deal_id = str(d["id"])
        if d.get("status") != "won" and deal_id not in known:
            continue  # not our business yet
        if known.get(deal_id) == d.get("update_time"):
            continue  # nothing changed since we last looked
        enqueue("sync_deal", deal_id, f"sync_deal:{deal_id}")
        queued += 1
    return queued