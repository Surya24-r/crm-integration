"""Run: python -m scripts.zoho_probe"""
from app.db import close_pool, open_pool
from app.zoho_client import ZohoClient

open_pool()
z = ZohoClient()

org = z.get("/organizations")["organizations"][0]
print("Org:", org.get("name"), "| base currency:", org.get("currency_code"),
      "| country:", org.get("country_code"))

print("\nTaxes:")
for t in z.get("/settings/taxes").get("taxes", []):
    print(" ", t.get("tax_id"), "|", t.get("tax_name"), "|", t.get("tax_percentage"), "%")

print("\nCurrencies:", [c.get("currency_code") for c in z.get("/settings/currencies").get("currencies", [])])

print("\nFirst items:")
for i in z.get("/items", params={"per_page": 10}).get("items", []):
    print(" ", i.get("item_id"), "|", i.get("name"))
close_pool()