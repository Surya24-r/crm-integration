"""Adds the payment and void scenarios on top of the seeded deals, using the same code
paths the app uses. Run after the seeded deals have invoices in Zoho:
    python -m scripts.seed_zoho_actions"""
from app.db import close_pool, fetch_all, open_pool
from app.deps import zoho
from app.process_invoices import record_payment
from app.reconcile import reconcile_all

PAY_DEALS = 6  # first six seeded deals get a partial payment on milestone 1


def main() -> None:
    open_pool()
    try:
        rows = fetch_all(
            """select m.crm_deal_id, m.seq, m.amount_minor, m.zoho_invoice_id
               from milestones m join deals d on d.crm_deal_id = m.crm_deal_id
               where left(d.title, 4) = 'SEED' and m.zoho_invoice_id is not null
               order by m.crm_deal_id, m.seq""")
        by_deal: dict[str, list[dict]] = {}
        for r in rows:
            by_deal.setdefault(r["crm_deal_id"], []).append(r)
        deal_ids = list(by_deal)
        print(f"seeded deals with invoices: {len(deal_ids)}")

        # Partial payments: a third of milestone 1 received
        for deal_id in deal_ids[:PAY_DEALS]:
            m1 = next((r for r in by_deal[deal_id] if r["seq"] == 1), None)
            if not m1:
                continue
            try:
                pay = record_payment(deal_id, 1, m1["amount_minor"] // 3, f"SEED-PAY-{deal_id}-M1")
                print("paid   deal", deal_id, "payment", pay.get("payment_id"))
            except Exception as e:
                print("paid   deal", deal_id, "FAILED:", e)

        # Void: cancel the milestone 2 invoice of one later deal (Zoho keeps the history)
        target = next((d for d in deal_ids[PAY_DEALS:]
                       if any(r["seq"] == 2 for r in by_deal[d])), None)
        if target:
            inv2 = next(r for r in by_deal[target] if r["seq"] == 2)["zoho_invoice_id"]
            try:
                zoho.post(f"/invoices/{inv2}/status/void", deal_id=target)
                print("voided milestone 2 invoice for deal", target)
            except Exception as e:
                print("void   deal", target, "FAILED:", e)
        else:
            print("no suitable deal found for a void")

        print("reconciled deals:", reconcile_all())
    finally:
        close_pool()


if __name__ == "__main__":
    main()