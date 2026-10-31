"""Pure customer-matching logic (no network), so it can be unit tested."""
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

LEGAL = {"llc", "ltd", "limited", "fzco", "fze", "fz", "llp", "inc", "co", "company",
         "pjsc", "psc", "est", "establishment", "corp", "corporation"}
SIMILAR = 0.85


def normalize_name(name: str | None) -> str:
    s = (name or "").lower().replace("&", " and ").replace(".", "")
    tokens = re.sub(r"[^a-z0-9]+", " ", s).split()
    while tokens and tokens[-1] in LEGAL:
        tokens.pop()
    return " ".join(tokens)


@dataclass
class MatchResult:
    kind: str  # 'match' | 'none' | 'ambiguous'
    matches: list = field(default_factory=list)


def _names(c: dict) -> list[str]:
    return [normalize_name(c.get("contact_name")), normalize_name(c.get("company_name"))]


def classify(candidates: list[dict], org_name: str, trn: str | None = None) -> MatchResult:
    """- exactly one exact name match      -> match
       - several exact matches            -> ambiguous (TRN breaks the tie when it can)
       - no exact but similar names exist -> ambiguous (a person decides)
       - nothing close                    -> none (safe to create)"""
    target = normalize_name(org_name)
    if not target:
        raise ValueError("organization name is empty")

    exact = [c for c in candidates if target in _names(c)]
    if len(exact) > 1 and trn:
        by_trn = [c for c in exact if (c.get("tax_reg_no") or "").strip() == trn.strip()]
        if len(by_trn) == 1:
            exact = by_trn
    if len(exact) == 1:
        return MatchResult("match", exact)
    if len(exact) > 1:
        return MatchResult("ambiguous", exact)

    similar = [c for c in candidates
               if any(n and SequenceMatcher(None, n, target).ratio() >= SIMILAR for n in _names(c))]
    if similar:
        return MatchResult("ambiguous", similar)
    return MatchResult("none")