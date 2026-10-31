import base64
import hashlib
import json
import secrets
import threading
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, Header, HTTPException
from psycopg.types.json import Jsonb

from app.config import settings
from app.collections_page import router as collections_router
from app.deal_page import router as deal_router
from app.db import close_pool, execute, fetch_one, open_pool
from app.jobs import enqueue, requeue_deal_jobs
from app.poller import poll_once
from app.log_page import router as log_router
from app.worker import run_worker
from app.errors import DataError
from app.home_page import router as home_router
from app.money import to_minor
from app.reconcile import reconcile_all
from app.process_invoices import record_payment, schedule_due_invoices
from app.zoho_client import ZohoError

POLL_SECONDS = 300
stop_event = threading.Event()


RECONCILE_EVERY = 12  # minutes


def poll_loop() -> None:
    tick = 0
    while not stop_event.is_set():
        try:
            poll_once()
            schedule_due_invoices()
            if tick % RECONCILE_EVERY == 0:
                reconcile_all()
        except Exception as e:  # never let the poller die
            print("poll error:", e)
        tick += 1
        stop_event.wait(POLL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    stop_event.clear()
    threads = [threading.Thread(target=run_worker, args=(stop_event,), daemon=True),
               threading.Thread(target=poll_loop, daemon=True)]
    for t in threads:
        t.start()
    yield
    stop_event.set()
    close_pool()


app = FastAPI(title="CRM <-> Zoho Books integration", lifespan=lifespan)
app.include_router(log_router)
app.include_router(deal_router)
app.include_router(collections_router)
app.include_router(home_router)


def _check_basic(authorization: str | None) -> None:
    """Pipedrive webhooks are registered with HTTP basic auth (user 'pipedrive')."""
    expected = base64.b64encode(f"pipedrive:{settings.webhook_secret}".encode()).decode()
    if not authorization or not secrets.compare_digest(authorization, f"Basic {expected}"):
        raise HTTPException(401, "bad credentials")


def _check_admin(key: str | None) -> None:
    if not key or not secrets.compare_digest(key, settings.webhook_secret):
        raise HTTPException(401, "bad admin key")


def _event_id(payload: dict) -> str:
    clean = json.loads(json.dumps(payload))
    for k in ("retry", "attempt"):
        (clean.get("meta") or {}).pop(k, None)
    return hashlib.sha256(json.dumps(clean, sort_keys=True).encode()).hexdigest()


def _deal_id(payload: dict) -> str | None:
    cur = payload.get("current") or payload.get("data") or {}
    meta = payload.get("meta") or {}
    did = cur.get("id") or meta.get("entity_id") or meta.get("id")
    return str(did) if did is not None else None


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/webhooks/crm")
def crm_webhook(payload: dict = Body(...), authorization: str | None = Header(None)):
    """Store the event, queue a job, return. Never talks to Zoho, so closing a deal
    in the CRM never waits on it."""
    _check_basic(authorization)
    deal_id = _deal_id(payload)
    if not deal_id:
        return {"ignored": "no deal id"}
    inserted = fetch_one(
        """insert into webhook_events (event_id, source, payload) values (%s, 'crm', %s)
           on conflict do nothing returning event_id""",
        (_event_id(payload), Jsonb(payload)),
    )
    if inserted is None:
        return {"duplicate": True}
    enqueue("sync_deal", deal_id, f"sync_deal:{deal_id}")
    return {"queued": deal_id}


@app.post("/admin/poll")
def admin_poll(x_admin_key: str | None = Header(None)):
    _check_admin(x_admin_key)
    return {"queued": poll_once()}


@app.post("/deals/{deal_id}/retry")
def retry_deal(deal_id: str, x_admin_key: str | None = Header(None)):
    """'Retry after a fix' button."""
    _check_admin(x_admin_key)
    execute("update deals set state = case when state = 'FAILED' then 'NEW' else state end, "
            "last_error = null where crm_deal_id = %s", (deal_id,))
    requeue_deal_jobs(deal_id)
    enqueue("sync_deal", deal_id, f"sync_deal:{deal_id}")
    return {"requeued": deal_id}


@app.post("/deals/{deal_id}/resolve-customer")
def resolve_customer(deal_id: str, body: dict = Body(...), x_admin_key: str | None = Header(None)):
    """A person decides when several Zoho customers could match.
    Body: {"zoho_contact_id": "..."} to use one, or {"create_new": true}."""
    _check_admin(x_admin_key)
    deal = fetch_one("select * from deals where crm_deal_id = %s", (deal_id,))
    if not deal:
        raise HTTPException(404, "unknown deal")
    candidates = (deal["metrics"] or {}).get("customer_candidates") or []
    if deal["zoho_customer_id"] or not candidates:
        raise HTTPException(400, "no pending customer decision for this deal")

    if body.get("zoho_contact_id"):
        if body["zoho_contact_id"] not in [c["contact_id"] for c in candidates]:
            raise HTTPException(400, "contact is not one of the candidates")
        execute("update deals set zoho_customer_id = %s where crm_deal_id = %s",
                (body["zoho_contact_id"], deal_id))
    elif body.get("create_new") is True:
        execute("""update deals set metrics = metrics || '{"force_create_customer": true}'::jsonb
                   where crm_deal_id = %s""", (deal_id,))
    else:
        raise HTTPException(400, "send zoho_contact_id or create_new")

    execute("""update deals set needs_review = false, review_reason = null, last_error = null,
                      metrics = metrics - 'customer_candidates', updated_at = now()
               where crm_deal_id = %s""", (deal_id,))
    enqueue("process_deal", deal_id, f"process_deal:{deal_id}")
    return {"resolved": deal_id}

@app.post("/deals/{deal_id}/payments")
def record_payment_endpoint(deal_id: str, body: dict = Body(...),
                            x_admin_key: str | None = Header(None)):
    """Body: {"milestone_seq": 1, "amount": 30000, "payment_key": "unique-key"}.
    The payment_key makes the call safe to repeat."""
    _check_admin(x_admin_key)
    try:
        pay = record_payment(deal_id, int(body["milestone_seq"]), to_minor(body["amount"]),
                             str(body["payment_key"]))
    except (DataError, ZohoError) as e:
        raise HTTPException(400, str(e))
    return {"payment_id": pay.get("payment_id")}