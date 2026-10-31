import threading
import traceback

from app import jobs
from app.crm_client import CrmError
from app.handlers import HANDLERS
from app.sync_deal import report_failure
from app.zoho_client import ZohoDailyLimit, ZohoError

MAX_ATTEMPTS = 8


def backoff(attempts: int) -> int:
    return min(30 * 2 ** max(attempts - 1, 0), 3600)


def run_worker(stop: threading.Event) -> None:
    while not stop.is_set():
        job = jobs.claim_next()
        if not job:
            stop.wait(2)
            continue
        try:
            HANDLERS[job["type"]](job)
            jobs.complete(job["id"])
        except ZohoDailyLimit as e:
            # not the job's fault: wait an hour without using up an attempt
            jobs.retry_later(job["id"], 3600, str(e), refund_attempt=True)
        except (ZohoError, CrmError) as e:
            if e.retryable and job["attempts"] < MAX_ATTEMPTS:
                delay = e.retry_after or backoff(job["attempts"])
                jobs.retry_later(job["id"], delay, str(e))
            else:
                jobs.fail(job["id"], str(e))
                report_failure(job["crm_deal_id"], str(e))
        except Exception as e:  # unexpected bug: retry a few times, then surface it
            traceback.print_exc()
            if job["attempts"] < 3:
                jobs.retry_later(job["id"], backoff(job["attempts"]), repr(e))
            else:
                jobs.fail(job["id"], repr(e))
                report_failure(job["crm_deal_id"], f"Unexpected error: {e!r}")