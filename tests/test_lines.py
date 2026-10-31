from app.lines import build_lines, line_total_minor, lines_total_minor


def test_line_total():
    assert line_total_minor(1, 12_000_000) == 12_000_000
    assert line_total_minor(2.5, 1_000) == 2_500


def test_unmapped_products_are_reported_never_guessed():
    products = [{"crm_product": "A", "quantity": 1, "unit_price_minor": 100},
                {"crm_product": "B", "quantity": 1, "unit_price_minor": 200}]
    lines, missing = build_lines(products, {"A": "item-a"})
    assert missing == ["B"]
    assert [l["item_id"] for l in lines] == ["item-a"]


def test_total_of_lines():
    products = [{"crm_product": "A", "quantity": 2, "unit_price_minor": 500},
                {"crm_product": "B", "quantity": 1, "unit_price_minor": 250}]
    lines, _ = build_lines(products, {"A": "a", "B": "b"})
    assert lines_total_minor(lines) == 1250