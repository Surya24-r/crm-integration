"""Seeds Pipedrive with 15 customers and 20 Won deals with varied go-live dates.
Run: python -m scripts.seed_crm
Safe to re-run: deals whose title already exists are skipped."""
import random
from datetime import date, timedelta

from app.crm_client import CrmClient
from app.db import close_pool, open_pool

random.seed(7)  # repeatable data

PRODUCT = "ERP Implementation Services"
ORGS = [
    "Al Noor Logistics", "Gulf Steel Works", "Emirates Dairy Co", "Falcon Retail Group",
    "Sahara Medical Supplies", "Marina Hospitality", "Dubai Textile House", "Oasis Construction",
    "Pearl Marine Services", "Desert Bloom Foods", "Creekside Auto", "Nova Tech Solutions",
    "Crescent Printing", "Horizon Realty", "Jebel Ali Freight",
]
NETS = [40000, 60000, 85000, 120000, 150000, 210000]          # AED, excluding VAT
GOLIVE_OFFSETS = [-200, -120, -30, 14, 45, 90, 180]          # days from today


def random_trn() -> str:
    return "100" + "".join(str(random.randint(0, 9)) for _ in range(12))


def main() -> None:
    open_pool()
    crm = CrmClient()
    keys = crm.field_keys(refresh=True)
    trn_key, golive_key = keys["Customer TRN"], keys["Go-Live Date"]

    products = crm.get("/products", params={"limit": 500}).get("data") or []
    pid = next((p["id"] for p in products if p["name"] == PRODUCT), None)
    if pid is None:
        pid = crm.post("/products", json_body={
            "name": PRODUCT, "prices": [{"price": 0, "currency": "AED"}]})["data"]["id"]
        print("created product", PRODUCT)

    org_ids = {o["name"]: o["id"] for o in (crm.get("/organizations", params={"limit": 500}).get("data") or [])}
    for name in ORGS:
        if name not in org_ids:
            org_ids[name] = crm.post("/organizations", json_body={"name": name})["data"]["id"]

    existing = {d["title"] for d in
                (crm.get("/deals", params={"limit": 500, "status": "all_not_deleted"}).get("data") or [])}

    for i in range(20):  # 20 deals over 15 customers: five customers get two deals
        org = ORGS[i % len(ORGS)]
        title = f"SEED {org} #{i + 1}"
        if title in existing:
            print("exists ", title)
            continue
        net = random.choice(NETS)
        golive = date.today() + timedelta(days=random.choice(GOLIVE_OFFSETS))
        deal_id = crm.post("/deals", json_body={
            "title": title, "value": net, "currency": "AED", "org_id": org_ids[org],
        })["data"]["id"]
        crm.post(f"/deals/{deal_id}/products", json_body={
            "product_id": pid, "item_price": net, "quantity": 1})
        crm.put(f"/deals/{deal_id}", json_body={
            trn_key: random_trn(), golive_key: golive.isoformat(), "status": "won"})
        print("created", deal_id, title, net, golive.isoformat())

    close_pool()


if __name__ == "__main__":
    main()