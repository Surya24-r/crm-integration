"""Writes to CRM fields the integration owns, and only when the value changed."""


def _norm(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return round(float(v), 2)
    return str(v)


def write_owned(crm, deal: dict, values: dict) -> dict:
    """values: {custom field name: new value}. `deal` is the deal as just fetched
    from the CRM, so it holds the current values. Returns what was actually written."""
    changes = {}
    for name, new in values.items():
        key = crm.field_key(name)
        if _norm(deal.get(key)) != _norm(new):
            changes[key] = new
    if changes:
        crm.put(f"/deals/{deal['id']}", deal_id=str(deal["id"]), json_body=changes)
    return changes