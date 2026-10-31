"""Which milestones are due to be invoiced. Pure logic, so it is unit tested."""


def due_milestones(milestones: list[dict], today) -> list[dict]:
    """Milestones that are due and not yet invoiced, in order.
    Stops at the first milestone that is not due yet, so later ones never jump ahead."""
    out = []
    for m in milestones:
        if m["zoho_invoice_id"]:
            continue
        if m["due_date"] is None or m["due_date"] > today:
            break
        out.append(m)
    return out