"""Job handler: customer -> items -> sales order. Every step is idempotent:
it first looks for what already exists (by stored id, then by search) before creating."""
from psycopg.types.json import Jsonb

from app import zoho_books
from app.config import settings
from app.crm_sync import write_owned
from app.customer_match import classify
from app.db import execute, fetch_all, fetch_one
from app.deps import crm, zoho
from app.errors import DataError
from app.lines import build_lines, lines_total_minor
from app.money import from_minor, to_minor, vat_of


def _deal_url(deal_id: str) -> str:
    return f"{settings.crm_base_url.split('/api/')[0]}/deal/{deal_id}"


def _so_url(so_id: str) -> str:
    return f"{settings.zoho_app_url}/{settings.zoho_org_id}#/salesorders/{so_id}"


def _crm_write(deal_id: str, values: dict) -> None:
    d = crm.get(f"/deals/{deal_id}", deal_id=deal_id)["data"]
    write_owned(crm, d, values)


def _review(deal_id: str, reason: str, metrics_patch: dict | None = None) -> None:
    execute(
        """update deals set needs_review = true, review_reason = %s, state = 'NEEDS_REVIEW',
                  metrics = metrics || %s, updated_at = now() where crm_deal_id = %s""",
        (reason, Jsonb(metrics_patch or {}), deal_id),
    )
    _crm_write(deal_id, {"Zoho Sync Status": "Needs review", "Zoho Sync Error": reason})


def _resolve_customer(deal: dict) -> str | None:
    """Returns the Zoho customer id, or None when a person must decide."""
    deal_id = deal["crm_deal_id"]
    candidates = zoho_books.find_contact_candidates(zoho, deal["org_name"], deal_id)
    result = classify(candidates, deal["org_name"], deal["tax_number"])

    if result.kind == "match":
        return result.matches[0]["contact_id"]
    forced = (deal["metrics"] or {}).get("force_create_customer")
    if result.kind == "none" or forced:
        return zoho_books.create_contact(zoho, deal, _deal_url(deal_id))

    names = ", ".join(c["contact_name"] for c in result.matches[:5])
    _review(deal_id,
            f"Several Zoho Books customers could match '{deal['org_name']}': {names}. "
            "A person must pick one or create a new customer.",
            {"customer_candidates": [{"contact_id": c["contact_id"], "contact_name": c["contact_name"]}
                                     for c in result.matches]})
    return None


def handle_process_deal(job: dict) -> None:
    deal_id = job["crm_deal_id"]
    deal = fetch_one("select * from deals where crm_deal_id = %s", (deal_id,))
    if not deal or deal["crm_status"] != "won" or deal["needs_review"]:
        return  # nothing to do, or waiting for a person
    if deal["zoho_so_id"] and deal["state"] in ("SO_OK", "INVOICING", "DONE"):
        return  # sales-order stage finished; invoicing takes over from here

    # ---- 1. customer ----
    customer_id = deal["zoho_customer_id"]
    if not customer_id:
        customer_id = _resolve_customer(deal)
        if not customer_id:
            return
        execute("update deals set zoho_customer_id = %s, state = 'CUSTOMER_OK', updated_at = now() "
                "where crm_deal_id = %s", (customer_id, deal_id))

    # ---- 2. sales order ----
    so_id = deal["zoho_so_id"]
    if so_id:
        so = zoho.get(f"/salesorders/{so_id}", deal_id=deal_id)["salesorder"]
    else:
        products = fetch_all(
            "select crm_product, quantity, unit_price_minor from deal_products "
            "where crm_deal_id = %s order by id", (deal_id,))
        if not products:
            raise DataError("Deal has no products. Add them in the CRM, then retry.")
        item_map = {r["crm_product"]: r["zoho_item_id"]
                    for r in fetch_all("select crm_product, zoho_item_id from product_item_map")}
        lines, missing = build_lines(products, item_map)
        if missing:
            raise DataError("Not mapped to a Zoho Books item: " + ", ".join(sorted(set(missing)))
                            + ". Add them to product_item_map, then retry.")
        lines_total = lines_total_minor(lines)
        if lines_total != deal["net_amount_minor"]:
            raise DataError(f"Product lines total {lines_total / 100:.2f} but deal value is "
                            f"{deal['net_amount_minor'] / 100:.2f}. Fix the deal, then retry.")

        reference = f"CRM-DEAL-{deal_id}"
        so = (zoho_books.find_sales_order(zoho, reference, deal_id)
              or zoho_books.create_sales_order(zoho, deal, customer_id, lines, _deal_url(deal_id)))
        so_id = so["salesorder_id"]
        # store the id immediately: from here a crash can never lead to a second sales order
        execute(
            """update deals set zoho_so_id = %s, metrics = metrics || %s, updated_at = now()
               where crm_deal_id = %s""",
            (so_id, Jsonb({"so_number": so.get("salesorder_number")}), deal_id),
        )

    # ---- 3. money check: our expected total must equal Zoho's total ----
    expected = deal["net_amount_minor"] + vat_of(deal["net_amount_minor"], deal["vat_rate_bp"])
    actual = to_minor(so["total"])
    if actual != expected:
        _review(deal_id, f"Zoho sales order total {actual / 100:.2f} does not match the expected "
                         f"{expected / 100:.2f} (net + VAT). Check tax settings, then retry.")
        return

    # ---- 4. confirm the sales order so it can be invoiced ----
    if so.get("status") == "draft":
        zoho.post(f"/salesorders/{so_id}/status/open", deal_id=deal_id)

    execute("update deals set so_total_minor = %s, state = 'SO_OK', last_error = null, "
            "updated_at = now() where crm_deal_id = %s", (actual, deal_id))

    # ---- 5. show it on the deal (traceability) ----
    total = float(from_minor(actual))
    _crm_write(deal_id, {
        "Zoho Customer ID": customer_id,
        "Zoho Sales Order": f"{so.get('salesorder_number')} {_so_url(so_id)}",
        "Zoho SO Total": total,
        "Zoho % Invoiced": 0,
        "Zoho % Collected": 0,
        "Zoho Invoiced Unpaid": 0,
        "Zoho Not Yet Invoiced": total,
        "Zoho Sync Status": "Sales order created",
        "Zoho Sync Error": "",
    })