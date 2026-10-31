"""Run: python -m scripts.invoice_probe. Lists recent sales orders and invoices so
you can confirm the fields the integration relies on."""
from app.db import close_pool, open_pool
from app.zoho_client import ZohoClient

open_pool()
z = ZohoClient()
sos = z.get("/salesorders", params={"per_page": 3}).get("salesorders", [])
print("Sales orders:", [(s["salesorder_number"], s["status"], s["total"]) for s in sos])
invs = z.get("/invoices", params={"per_page": 3}).get("invoices", [])
print("Invoices:", [(i["invoice_number"], i["status"], i["total"]) for i in invs])
pays = z.get("/customerpayments", params={"per_page": 3}).get("customerpayments", [])
print("Payments:", len(pays))
close_pool()