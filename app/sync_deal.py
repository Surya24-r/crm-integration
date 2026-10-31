"""Job handler: load the current deal from the CRM and bring our database up to date.
Never trusts the event payload (events can be duplicated or out of order)."""
from datetime import date, timedelta

from app.crm_client import CrmError
from app.crm_sync import write_owned
from app.db import execute, fetch_one, get_conn
from app.deps import crm
from app.money import plan_milestones, to_minor

# seq, label, percent (basis points), trigger type, trigger days
MILESTONES = [
    (1, "50% on signing", 5000, "signing", 0),
    (2, "30% at go-live", 3000, "go_live", 0),
    (3, "20% ninety days after go-live", 2000, "go_live_plus_days", 90),
]
PCTS = [m[2] for m in MILESTONES]


def _flag_review(deal_id: str, d: dict, reason: str) -> None:
    execute(
        """update deals set needs_review = true, review_reason = %s,
                  crm_update_time = %s, updated_at = now()
           where crm_deal_id = %s""",
        (reason, d.get("update_time"), deal_id),
    )
    write_owned(crm, d, {"Zoho Sync Status": "Needs review", "Zoho Sync Error": reason})


def _store_products(deal_id: str) -> None:
    try:
        items = crm.get(f"/deals/{deal_id}/products", deal_id=deal_id).get("data") or []
    except CrmError as e:
        if e.retryable:
            raise
        items = []  # product feature off or none attached; processing step will flag it
    with get_conn() as conn:
        conn.execute("delete from deal_products where crm_deal_id = %s", (deal_id,))
        for it in items:
            conn.execute(
                """insert into deal_products (crm_deal_id, crm_product, quantity, unit_price_minor)
                   values (%s, %s, %s, %s)""",
                (deal_id, it.get("name"), it.get("quantity") or 1, to_minor(it.get("item_price") or 0)),
            )


def _store_milestones(deal: dict, won_day: date) -> None:
    plan = plan_milestones(deal["net_amount_minor"], deal["vat_rate_bp"], PCTS)
    go_live = deal["go_live_date"]
    with get_conn() as conn:
        conn.execute(
            "delete from milestones where crm_deal_id = %s and zoho_invoice_id is null",
            (deal["crm_deal_id"],),
        )
        for (seq, label, pct, trigger, days), p in zip(MILESTONES, plan):
            if seq == 1:
                due = won_day
            elif go_live:
                due = go_live + timedelta(days=days)
            else:
                due = None
            conn.execute(
                """insert into milestones
                   (crm_deal_id, seq, label, pct_bp, amount_minor, net_minor,
                    trigger_type, trigger_days, reached_at, due_date)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   on conflict (crm_deal_id, seq) do nothing""",
                (deal["crm_deal_id"], seq, label, pct, p["gross"], p["net"], trigger, days,
                 deal["won_at"] if seq == 1 else None, due),
            )


def handle_sync_deal(job: dict) -> None:
    deal_id = job["crm_deal_id"]
    d = crm.get(f"/deals/{deal_id}", deal_id=deal_id)["data"]
    existing = fetch_one("select * from deals where crm_deal_id = %s", (deal_id,))
    status = d.get("status")

    # ---- not won (open / lost / reopened) ----
    if status != "won":
        if existing and existing["zoho_so_id"]:
            _flag_review(deal_id, d,
                         f"Deal is now '{status}' but a sales order already exists in Zoho Books. "
                         "Finance must decide.")
        elif existing:
            execute("update deals set crm_status = %s, crm_update_time = %s, updated_at = now() "
                    "where crm_deal_id = %s", (status, d.get("update_time"), deal_id))
        return

    # ---- won ----
    org = d.get("org_id")
    org_name = d.get("org_name") or (org.get("name") if isinstance(org, dict) else None)
    if not org_name:
        raise CrmError("Deal has no organization, so no customer can be created.", retryable=False)

    net = to_minor(d.get("value") or 0)
    if net <= 0:
        raise CrmError("Deal value must be greater than zero.", retryable=False)

    currency = d.get("currency") or "AED"
    trn = d.get(crm.field_key("Customer TRN")) or None
    go_live = d.get(crm.field_key("Go-Live Date")) or None
    won_time = d.get("won_time")  # 'YYYY-MM-DD HH:MM:SS' (UTC) or None

    has_so = bool(existing and existing["zoho_so_id"])
    if has_so and existing["net_amount_minor"] != net:
        _flag_review(deal_id, d,
                     f"Deal amount changed from {existing['net_amount_minor'] / 100:.2f} to "
                     f"{net / 100:.2f} after the sales order was created. Finance must review.")

    execute(
        """
        insert into deals (crm_deal_id, title, org_name, tax_number, currency, net_amount_minor,
                           stage, crm_status, won_at, go_live_date, crm_update_time)
        values (%s, %s, %s, %s, %s, %s, %s, %s, coalesce(%s::timestamptz, now()), %s, %s)
        on conflict (crm_deal_id) do update set
          title = excluded.title,
          org_name = excluded.org_name,
          tax_number = excluded.tax_number,
          stage = excluded.stage,
          crm_status = excluded.crm_status,
          won_at = coalesce(deals.won_at, excluded.won_at),
          go_live_date = excluded.go_live_date,
          crm_update_time = excluded.crm_update_time,
          currency = case when deals.zoho_so_id is null then excluded.currency else deals.currency end,
          net_amount_minor = case when deals.zoho_so_id is null
                                  then excluded.net_amount_minor else deals.net_amount_minor end,
          updated_at = now()
        """,
        (deal_id, d.get("title"), org_name, trn, currency, net, str(d.get("stage_id")),
         status, won_time, go_live, d.get("update_time")),
    )

    if not has_so:
        _store_products(deal_id)
        deal = fetch_one("select * from deals where crm_deal_id = %s", (deal_id,))
        _store_milestones(deal, deal["won_at"].date())
        fresh = existing is None or (existing["state"] == "NEW" and not existing["needs_review"])
        if fresh:
            write_owned(crm, d, {"Zoho Sync Status": "Queued", "Zoho Sync Error": ""})


def report_failure(deal_id: str | None, message: str) -> None:
    """Make a failure visible on the deal (database + CRM)."""
    if not deal_id:
        return
    execute("update deals set state = 'FAILED', last_error = %s, updated_at = now() "
            "where crm_deal_id = %s", (message[:1000], deal_id))
    try:
        d = crm.get(f"/deals/{deal_id}", deal_id=deal_id)["data"]
        write_owned(crm, d, {"Zoho Sync Status": "Failed", "Zoho Sync Error": message[:1000]})
    except Exception:
        pass  # visibility is best effort; the database row still shows it