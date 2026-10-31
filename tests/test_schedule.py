from datetime import date

from app.schedule import due_milestones

TODAY = date(2026, 10, 31)


def m(seq, due, invoice=None):
    return {"seq": seq, "due_date": due, "zoho_invoice_id": invoice}


def test_only_due_uninvoiced_milestones_are_returned():
    rows = [m(1, date(2026, 10, 1), "inv1"), m(2, date(2026, 10, 31)), m(3, date(2027, 1, 29))]
    assert [r["seq"] for r in due_milestones(rows, TODAY)] == [2]


def test_later_milestone_never_jumps_ahead_of_an_undue_one():
    rows = [m(1, date(2026, 11, 5)), m(2, date(2026, 10, 1))]
    assert due_milestones(rows, TODAY) == []


def test_missing_go_live_date_blocks_later_milestones():
    rows = [m(1, date(2026, 10, 1), "inv1"), m(2, None), m(3, None)]
    assert due_milestones(rows, TODAY) == []