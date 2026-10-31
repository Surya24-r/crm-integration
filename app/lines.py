"""Pure helpers: CRM product rows -> Zoho line items."""
from decimal import ROUND_HALF_UP, Decimal


def line_total_minor(quantity, unit_minor: int) -> int:
    return int((Decimal(str(quantity)) * unit_minor).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def build_lines(products: list[dict], item_map: dict[str, str]) -> tuple[list[dict], list[str]]:
    """Returns (lines, unmapped product names). An item is never guessed."""
    lines, missing = [], []
    for p in products:
        item_id = item_map.get(p["crm_product"])
        if not item_id:
            missing.append(p["crm_product"])
            continue
        lines.append({"item_id": item_id, "quantity": float(p["quantity"]),
                      "unit_minor": p["unit_price_minor"], "crm_product": p["crm_product"]})
    return lines, missing


def lines_total_minor(lines: list[dict]) -> int:
    return sum(line_total_minor(l["quantity"], l["unit_minor"]) for l in lines)