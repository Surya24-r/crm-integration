"""Money maths. All amounts are integer minor units (fils); never floats."""
from decimal import ROUND_HALF_UP, Decimal


def to_minor(amount) -> int:
    """120000 / '120000.50' / Decimal -> fils, rounded half up."""
    return int((Decimal(str(amount)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_minor(minor: int) -> Decimal:
    return Decimal(minor) / 100


def vat_of(net_minor: int, vat_bp: int) -> int:
    """VAT on a net amount, rounded half up. vat_bp is basis points (500 = 5%)."""
    return (net_minor * vat_bp + 5000) // 10000


def split_amount(total: int, pcts_bp: list[int]) -> list[int]:
    """Split total by basis-point percentages. The last part takes the remainder,
    so the parts always add up to the total exactly."""
    if not pcts_bp or any(p <= 0 for p in pcts_bp) or sum(pcts_bp) != 10000:
        raise ValueError("percentages must be positive and sum to 10000 basis points")
    parts = [(total * p + 5000) // 10000 for p in pcts_bp[:-1]]
    parts.append(total - sum(parts))
    return parts


def plan_milestones(net_minor: int, vat_bp: int, pcts_bp: list[int]) -> list[dict]:
    """Per-milestone net / vat / gross. Sums of each column equal the sales order's
    net / vat / gross exactly (remainder goes to the last milestone)."""
    nets = split_amount(net_minor, pcts_bp)
    total_vat = vat_of(net_minor, vat_bp)
    vats = [vat_of(n, vat_bp) for n in nets[:-1]]
    vats.append(total_vat - sum(vats))
    return [{"net": n, "vat": v, "gross": n + v} for n, v in zip(nets, vats)]