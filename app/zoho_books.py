"""Zoho Books operations (thin wrappers over ZohoClient)."""
from app.config import settings
from app.customer_match import normalize_name
from app.errors import DataError
from app.money import from_minor
from datetime import date as _date

_cache: dict = {}


def vat_tax_id(zoho, vat_bp: int) -> str:
    key = ("tax", vat_bp)
    if key not in _cache:
        pct = vat_bp / 100
        taxes = zoho.get("/settings/taxes").get("taxes") or []
        found = [t for t in taxes
                 if abs(float(t.get("tax_percentage", -1)) - pct) < 1e-9 and not t.get("is_inactive")]
        if len(found) > 1:
            found = [t for t in found if "standard" in t.get("tax_name", "").lower()] or found
        if len(found) != 1:
            raise DataError(f"Expected exactly one {pct}% tax in Zoho Books, found {len(found)}. "
                            "Check Settings > Taxes.")
        _cache[key] = found[0]["tax_id"]
    return _cache[key]


def currency_id(zoho, code: str) -> str | None:
    """None when the deal currency is the organisation's base currency."""
    if code == settings.zoho_base_currency:
        return None
    key = ("cur", code)
    if key not in _cache:
        rows = zoho.get("/settings/currencies").get("currencies") or []
        found = [c for c in rows if c.get("currency_code") == code]
        if not found:
            raise DataError(f"Currency {code} is not set up in Zoho Books.")
        _cache[key] = found[0]["currency_id"]
    return _cache[key]


def find_contact_candidates(zoho, org_name: str, deal_id: str) -> list[dict]:
    query = " ".join(normalize_name(org_name).split()[:2]) or org_name
    data = zoho.get("/contacts", deal_id=deal_id,
                    params={"contact_name_contains": query, "per_page": 200})
    return [c for c in (data.get("contacts") or [])
            if c.get("contact_type", "customer") == "customer" and c.get("status") != "inactive"]


def create_contact(zoho, deal: dict, deal_url: str) -> str:
    body = {
        "contact_name": deal["org_name"],
        "company_name": deal["org_name"],
        "contact_type": "customer",
        "customer_sub_type": "business",
        "notes": f"Created by the CRM integration from deal {deal['crm_deal_id']}: {deal_url}",
    }
    if deal["tax_number"]:
        body.update({"tax_treatment": "vat_registered", "tax_reg_no": deal["tax_number"]})
    return zoho.post("/contacts", deal_id=deal["crm_deal_id"], json_body=body)["contact"]["contact_id"]


def find_sales_order(zoho, reference: str, deal_id: str) -> dict | None:
    rows = zoho.get("/salesorders", deal_id=deal_id,
                    params={"reference_number": reference}).get("salesorders") or []
    rows = [r for r in rows if r.get("reference_number") == reference and r.get("status") != "void"]
    if len(rows) > 1:
        raise DataError(f"More than one sales order has reference {reference}. Finance must clean up.")
    return rows[0] if rows else None


def create_sales_order(zoho, deal: dict, customer_id: str, lines: list[dict], deal_url: str) -> dict:
    tax_id = vat_tax_id(zoho, deal["vat_rate_bp"])
    body = {
        "customer_id": customer_id,
        "reference_number": f"CRM-DEAL-{deal['crm_deal_id']}",
        "date": deal["won_at"].date().isoformat(),
        "place_of_supply": settings.zoho_place_of_supply,
        "notes": f"Created from CRM deal '{deal['title']}' ({deal_url})",
        "line_items": [
            {"item_id": l["item_id"], "quantity": l["quantity"],
             "rate": float(from_minor(l["unit_minor"])), "tax_id": tax_id}
            for l in lines
        ],
    }
    cur = currency_id(zoho, deal["currency"])
    if cur:
        body["currency_id"] = cur
    return zoho.post("/salesorders", deal_id=deal["crm_deal_id"], json_body=body)["salesorder"]



def find_invoice(zoho, reference: str, deal_id: str) -> dict | None:
    rows = zoho.get("/invoices", deal_id=deal_id,
                    params={"reference_number": reference}).get("invoices") or []
    rows = [r for r in rows if r.get("reference_number") == reference and r.get("status") != "void"]
    if len(rows) > 1:
        raise DataError(f"More than one invoice has reference {reference}. Finance must clean up.")
    return rows[0] if rows else None


def get_invoice(zoho, invoice_id: str, deal_id: str) -> dict:
    return zoho.get(f"/invoices/{invoice_id}", deal_id=deal_id)["invoice"]


def create_invoice(zoho, deal: dict, customer_id: str, so_id: str, seq: int, label: str,
                   net_minor: int, due: _date, item_id: str, reference: str, deal_url: str) -> dict:
    tax_id = vat_tax_id(zoho, deal["vat_rate_bp"])
    body = {
        "customer_id": customer_id,
        "reference_number": reference,
        "date": _date.today().isoformat(),
        "due_date": max(due, _date.today()).isoformat(),
        "salesorder_id": so_id,
        "place_of_supply": settings.zoho_place_of_supply,
        "notes": f"Milestone {seq}: {label}. CRM deal: {deal_url}",
        "line_items": [{
            "item_id": item_id,
            "name": label,
            "quantity": 1,
            "rate": float(from_minor(net_minor)),
            "tax_id": tax_id,
        }],
    }
    cur = currency_id(zoho, deal["currency"])
    if cur:
        body["currency_id"] = cur
    return zoho.post("/invoices", deal_id=deal["crm_deal_id"], json_body=body)["invoice"]


def find_payment(zoho, reference: str, deal_id: str) -> dict | None:
    rows = zoho.get("/customerpayments", deal_id=deal_id,
                    params={"reference_number": reference}).get("customerpayments") or []
    rows = [r for r in rows if r.get("reference_number") == reference]
    if len(rows) > 1:
        raise DataError(f"More than one payment has reference {reference}. Finance must clean up.")
    return rows[0] if rows else None


def create_payment(zoho, deal_id: str, customer_id: str, invoice_id: str,
                   amount_minor: int, reference: str) -> dict:
    amount = float(from_minor(amount_minor))
    body = {
        "customer_id": customer_id,
        "payment_mode": "banktransfer",
        "amount": amount,
        "date": _date.today().isoformat(),
        "reference_number": reference,
        "invoices": [{"invoice_id": invoice_id, "amount_applied": amount}],
    }
    return zoho.post("/customerpayments", deal_id=deal_id, json_body=body)["payment"]