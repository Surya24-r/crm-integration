"""Durable job queue on Postgres. Safe across crashes and duplicate events."""
from psycopg.types.json import Jsonb

from app.db import execute, get_conn

STALE_RUNNING_MINUTES = 5  # a job stuck in 'running' this long is picked up again


def enqueue(job_type: str, deal_id: str | None, dedupe_key: str, payload: dict | None = None) -> None:
    """Same dedupe_key never creates a second job:
    - queued/retry job: left alone (it will run anyway)
    - done/failed job: queued again
    - running job: flagged so it runs once more when it finishes"""
    execute(
        """
        insert into jobs (type, crm_deal_id, payload, dedupe_key)
        values (%s, %s, %s, %s)
        on conflict (dedupe_key) do update set
          status = case when jobs.status in ('done', 'failed') then 'queued' else jobs.status end,
          attempts = case when jobs.status in ('done', 'failed') then 0 else jobs.attempts end,
          run_after = case when jobs.status in ('done', 'failed') then now() else jobs.run_after end,
          payload = case when jobs.status = 'running'
                         then jobs.payload || '{"rerun": true}'::jsonb else jobs.payload end,
          updated_at = now()
        """,
        (job_type, deal_id, Jsonb(payload or {}), dedupe_key),
    )


def claim_next() -> dict | None:
    with get_conn() as conn:
        return conn.execute(
            """
            update jobs set status = 'running', attempts = attempts + 1, updated_at = now()
            where id = (
              select id from jobs
              where (status in ('queued', 'retry') and run_after <= now())
                 or (status = 'running'
                     and updated_at < now() - make_interval(mins => %s))
              order by run_after, id
              for update skip locked
              limit 1
            )
            returning *
            """,
            (STALE_RUNNING_MINUTES,),
        ).fetchone()


def complete(job_id: int) -> None:
    execute(
        """
        update jobs set
          status = case when payload->>'rerun' = 'true' then 'queued' else 'done' end,
          attempts = case when payload->>'rerun' = 'true' then 0 else attempts end,
          payload = payload - 'rerun',
          last_error = null, run_after = now(), updated_at = now()
        where id = %s
        """,
        (job_id,),
    )


def retry_later(job_id: int, delay_seconds: int, error: str, refund_attempt: bool = False) -> None:
    execute(
        """
        update jobs set status = 'retry', last_error = %s,
          run_after = now() + make_interval(secs => %s),
          attempts = case when %s then greatest(attempts - 1, 0) else attempts end,
          updated_at = now()
        where id = %s
        """,
        (error[:1000], delay_seconds, refund_attempt, job_id),
    )


def fail(job_id: int, error: str) -> None:
    execute(
        "update jobs set status = 'failed', last_error = %s, updated_at = now() where id = %s",
        (error[:1000], job_id),
    )


def requeue_deal_jobs(deal_id: str) -> None:
    """Used by the 'retry after a fix' button."""
    execute(
        """
        update jobs set status = 'queued', attempts = 0, run_after = now(), updated_at = now()
        where crm_deal_id = %s and status in ('failed', 'retry')
        """,
        (deal_id,),
    )