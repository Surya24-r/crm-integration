import pytest

from app.customer_match import classify, normalize_name


def c(cid, name, trn=None):
    return {"contact_id": cid, "contact_name": name, "company_name": name, "tax_reg_no": trn}


def test_normalize_drops_legal_suffix_and_punctuation():
    assert normalize_name("Al Noor Logistics L.L.C.") == "al noor logistics"
    assert normalize_name("Al-Noor  Logistics, LLC") == "al noor logistics"
    assert normalize_name("Gulf Trading Co LLC") == "gulf trading"


def test_single_exact_match():
    r = classify([c("1", "Al Noor Logistics LLC"), c("2", "Gulf Steel")], "Al Noor Logistics L.L.C.")
    assert r.kind == "match" and r.matches[0]["contact_id"] == "1"


def test_nothing_close_means_create():
    assert classify([c("2", "Gulf Steel")], "Al Noor Logistics").kind == "none"
    assert classify([], "Al Noor Logistics").kind == "none"


def test_two_exact_matches_need_a_person():
    r = classify([c("1", "Al Noor Logistics"), c("2", "Al Noor Logistics LLC")], "Al Noor Logistics")
    assert r.kind == "ambiguous" and len(r.matches) == 2


def test_trn_breaks_a_tie():
    cands = [c("1", "Al Noor Logistics", "100000000000001"), c("2", "Al Noor Logistics LLC", "100000000000002")]
    r = classify(cands, "Al Noor Logistics", trn="100000000000002")
    assert r.kind == "match" and r.matches[0]["contact_id"] == "2"


def test_similar_but_not_equal_needs_a_person():
    r = classify([c("1", "Al Noor Logistics")], "Al Noor Logistic")
    assert r.kind == "ambiguous"


def test_empty_name_is_rejected():
    with pytest.raises(ValueError):
        classify([], "LLC")