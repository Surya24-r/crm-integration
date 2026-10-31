"""Creates the custom deal fields in Pipedrive. Run: python -m scripts.setup_crm_fields"""
from app.crm_client import CrmClient
from app.crm_fields import ALL_FIELDS
from app.db import close_pool, open_pool

open_pool()
crm = CrmClient()

existing = crm.field_keys(refresh=True)
for name, field_type in ALL_FIELDS.items():
    if name in existing:
        print(f"exists   {name}")
        continue
    crm.post("/dealFields", json_body={"name": name, "field_type": field_type})
    print(f"created  {name} ({field_type})")

close_pool()