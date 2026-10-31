import pytest

from app.money import plan_milestones, split_amount, to_minor, vat_of

PCTS = [5000, 3000, 2000]


def test_to_minor():
    assert to_minor("120000") == 12_000_000
    assert to_minor(120000.5) == 12_000_050
    assert to_minor("10.005") == 1001  # half up


def test_vat():
    assert vat_of(12_000_000, 500) == 600_000


def test_assignment_example():
    plan = plan_milestones(12_000_000, 500, PCTS)
    assert [p["net"] for p in plan] == [6_000_000, 3_600_000, 2_400_000]
    assert [p["vat"] for p in plan] == [300_000, 180_000, 120_000]
    assert [p["gross"] for p in plan] == [6_300_000, 3_780_000, 2_520_000]
    assert sum(p["gross"] for p in plan) == 12_600_000  # SO total


@pytest.mark.parametrize("net", [1, 7, 99, 1_000_001, 12_345_679, 99_999_999])
def test_milestones_always_add_up_exactly(net):
    plan = plan_milestones(net, 500, PCTS)
    assert sum(p["net"] for p in plan) == net
    assert sum(p["vat"] for p in plan) == vat_of(net, 500)
    assert sum(p["gross"] for p in plan) == net + vat_of(net, 500)


def test_split_rejects_bad_percentages():
    with pytest.raises(ValueError):
        split_amount(1000, [5000, 3000])
    with pytest.raises(ValueError):
        split_amount(1000, [5000, 6000, -1000])