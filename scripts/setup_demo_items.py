"""Run: python -m scripts.setup_demo_items
Creates service items in Zoho Books (if missing) and maps CRM product names to them."""
from app.db import close_pool, execute, open_pool
from app.zoho_client import ZohoClient

PRODUCTS = ["ERP Implementation Services", "Annual Support Plan", "Training Workshop"]

open_pool()
z = ZohoClient()

for name in PRODUCTS:
    rows = z.get("/items", params={"name_contains": name}).get("items", [])
    exact = [r for r in rows if r.get("name") == name]
    if exact:
        item_id = exact[0]["item_id"]
        print("exists  ", name)
    else:
        body = {"name": name, "rate": 1000, "product_type": "service", "item_type": "sales"}
        item_id = z.post("/items", json_body=body)["item"]["item_id"]
        print("created ", name)
    execute(
        """insert into product_item_map (crm_product, zoho_item_id) values (%s, %s)
           on conflict (crm_product) do update set zoho_item_id = excluded.zoho_item_id""",
        (name, item_id),
    )
close_pool()