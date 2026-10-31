from datetime import date

from app.metrics import compute_metrics

TODAY = date(2026, 10, 31)


def inv(total, balance, due, status="sent"):
    return {"total_minor": total, "balance_minor": balance, "due_date": due, "status": status}


def test_partly_invoiced_and_partly_paid():
    invoices = [inv(6_300_000, 3_300_000, date(2026, 10, 1))]  # 63,000 invoiced, 30,000 paid
    m = compute_metrics(12_600_000, invoices, TODAY)
    assert m["invoiced_minor"] == 6_300_000
    assert m["collected_minor"] == 3_000_000
    assert m["not_invoiced_minor"] == 6_300_000
    assert m["pct_invoiced"] == 50.0
    assert m["overdue"] is True


def test_voided_invoice_is_ignored():
    invoices = [inv(6_300_000, 6_300_000, date(2026, 10, 1)),
                inv(6_300_000, 0, None, status="void")]
    m = compute_metrics(12_600_000, invoices, TODAY)
    assert m["invoiced_minor"] == 6_300_000
    assert m["not_invoiced_minor"] == 6_300_000


def test_fully_paid_is_not_overdue():
    m = compute_metrics(100, [inv(100, 0, date(2026, 1, 1))], TODAY)
    assert m["overdue"] is False and m["next_due_date"] is None