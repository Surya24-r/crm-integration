"""Run: python -m scripts.check_zoho_client"""
from app.db import close_pool, open_pool
from app.integration_log import calls_for_deal
from app.zoho_client import ZohoClient

open_pool()
client = ZohoClient()

body = client.get("/contacts", deal_id="TEST", params={"per_page": 1})
print("code:", body["code"], "| contacts returned:", len(body.get("contacts", [])))

body = client.get("/items", deal_id="TEST", params={"per_page": 1})
print("code:", body["code"], "| items returned:", len(body.get("items", [])))

print("Zoho calls logged for deal TEST:", calls_for_deal("TEST"))
close_pool()