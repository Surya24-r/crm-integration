"""Run: python -m scripts.check_crm"""
from app.crm_client import CrmClient
from app.db import close_pool, open_pool

open_pool()
crm = CrmClient()

me = crm.get("/users/me")["data"]
print("Connected as:", me["name"], "|", me["company_domain"])

deals = crm.get("/deals", params={"limit": 5, "status": "all_not_deleted"}).get("data") or []
print("Deals found:", len(deals))

keys = crm.field_keys(refresh=True)
print("Custom fields present:", sum(1 for n in keys if n.startswith("Zoho") or n in ("Customer TRN", "Go-Live Date")))
close_pool()