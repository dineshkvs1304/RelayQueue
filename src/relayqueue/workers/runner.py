import logging
import os
import signal
import socket
import threading
from time import perf_counter
from uuid import UUID

from prometheus_client import start_http_server

from relayqueue.core.logging_config import configure_logging
from relayqueue.database.connection import SessionLocal
from relayqueue.monitoring.metrics import (
    ACTIVE_JOBS,
    JOB_EXECUTION_DURATION,
    JOB_FAILURES,
    JOB_RETRIES,
    JOBS_PROCESSED,
    WORKERS,
)
from relayqueue.services.worker_registry_service import (
    record_heartbeat,
    register_worker,
    update_worker_status,
)
from relayqueue.services.worker_service import (
    claim_next_job,
    complete_job,
    fail_job,
    recover_expired_jobs,
    renew_job_lease,
)
from relayqueue.workers.handlers import execute_task

configure_logging()
logger = logging.getLogger(__name__)

LEASE_DURATION_SECONDS = 30
HEARTBEAT_INTERVAL_SECONDS = 10
POLL_INTERVAL_SECONDS = 2

# Each worker process can use its own Prometheus port.
WORKER_METRICS_PORT = int(os.getenv("RELAYQUEUE_WORKER_METRICS_PORT", "8001"))

_current_worker_status = "offline"


def register_this_worker() -> UUID:
    """Register this worker and return its database ID."""
    hostname = socket.gethostname()

    with SessionLocal() as db:
        worker = register_worker(
            db,
            name=f"relay-worker-{hostname}",
            hostname=hostname,
        )
        worker_id = worker.id

    logger.info("Worker registered successfully: %s", worker_id)
    return worker_id


def heartbeat_loop(
    worker_id: UUID,
    stop_event: threading.Event,
) -> None:
    """Send periodic heartbeats to the worker registry."""
    while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
        try:
            with SessionLocal() as db:
                worker = record_heartbeat(db, worker_id)

                if worker is None:
                    logger.error("Worker registration no longer exists")
                    return

            logger.info("Worker heartbeat recorded: %s", worker_id)

        except Exception:
            logger.exception("Worker heartbeat failed: %s", worker_id)


def process_one_job(worker_id: UUID) -> bool:
    """Claim and execute one job for this worker."""

    with SessionLocal() as db:
        claimed = claim_next_job(
            db,
            worker_id,
            lease_duration_seconds=LEASE_DURATION_SECONDS,
        )

        if claimed is None:
            return False

        job, attempt = claimed

        job_id = job.id
        attempt_id = attempt.id
        task_type = job.task_type
        payload = job.payload
        attempt_number = attempt.attempt_number

    logger.info(
        "Claimed job %s | worker %s | attempt %s",
        job_id,
        worker_id,
        attempt_number,
    )

    ACTIVE_JOBS.inc()
    execution_start = perf_counter()

    lease_stop_event = threading.Event()
    lease_lost_event = threading.Event()

    def renew_lease_loop() -> None:
        """Renew the job lease while its handler is executing."""
        while not lease_stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
            try:
                with SessionLocal() as lease_db:
                    renew_job_lease(
                        lease_db,
                        job_id,
                        attempt_id,
                        worker_id,
                        lease_duration_seconds=LEASE_DURATION_SECONDS,
                    )

                logger.info("Lease renewed for job %s", job_id)

            except Exception:
                logger.exception("Lease renewal failed for job %s", job_id)
                lease_lost_event.set()
                return

    lease_thread = threading.Thread(
        target=renew_lease_loop,
        name=f"lease-renewal-{job_id}",
        daemon=True,
    )

    lease_thread.start()

    try:
        execute_task(task_type, payload)

        lease_stop_event.set()
        lease_thread.join()

        if lease_lost_event.is_set():
            logger.error(
                "Job %s finished, but its lease was lost. It will not be marked completed.",
                job_id,
            )
            return True

        with SessionLocal() as result_db:
            complete_job(result_db, job_id, attempt_id)

        JOBS_PROCESSED.labels(status="completed").inc()

        logger.info("Job %s completed successfully", job_id)

    except Exception as exc:
        JOB_FAILURES.inc()

        logger.exception(
            "Job %s failed on attempt %s",
            job_id,
            attempt_number,
        )

        lease_stop_event.set()
        lease_thread.join()

        if lease_lost_event.is_set():
            logger.error(
                "Cannot safely record failure for job %s because its lease was lost.",
                job_id,
            )
            return True

        try:
            with SessionLocal() as result_db:
                outcome = fail_job(
                    result_db,
                    job_id,
                    attempt_id,
                    str(exc),
                )

            if outcome == "retrying":
                JOB_RETRIES.inc()
                logger.info("Job %s scheduled for retry", job_id)

            else:
                JOBS_PROCESSED.labels(status="dead_letter").inc()
                logger.error("Job %s moved to dead-letter state", job_id)

        except Exception:
            logger.exception("Could not record failure for job %s", job_id)

    finally:
        lease_stop_event.set()
        lease_thread.join()

        JOB_EXECUTION_DURATION.observe(perf_counter() - execution_start)

        ACTIVE_JOBS.dec()

    return True


def set_worker_status(worker_id: UUID, status: str) -> None:
    """Update the worker's lifecycle status and Prometheus gauge."""
    global _current_worker_status

    with SessionLocal() as db:
        worker = update_worker_status(db, worker_id, status)

        if worker is None:
            logger.warning(
                "Cannot set worker %s to %s: worker not found",
                worker_id,
                status,
            )
            return

    WORKERS.labels(status=_current_worker_status).set(0)
    WORKERS.labels(status=status).set(1)
    _current_worker_status = status

    logger.info("Worker %s status changed to %s", worker_id, status)


def start_worker(
    poll_interval: float = POLL_INTERVAL_SECONDS,
) -> None:
    """Start a worker with graceful shutdown and Prometheus monitoring."""
    global _current_worker_status

    worker_id = register_this_worker()

    _current_worker_status = "active"
    WORKERS.labels(status="active").set(1)

    metrics_server = None
    metrics_thread = None

    heartbeat_stop_event = threading.Event()
    shutdown_event = threading.Event()

    previous_handlers = {}

    def handle_shutdown(signum, frame) -> None:
        logger.info("Shutdown signal received: %s", signum)
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, handle_shutdown)
        except ValueError:
            logger.warning(
                "Could not install handler for signal %s outside the main thread",
                sig,
            )

    try:
        metrics_server, metrics_thread = start_http_server(WORKER_METRICS_PORT)

        logger.info(
            "Worker Prometheus metrics available on port %s",
            WORKER_METRICS_PORT,
        )

        heartbeat_thread = threading.Thread(
            target=heartbeat_loop,
            args=(worker_id, heartbeat_stop_event),
            name=f"worker-heartbeat-{worker_id}",
            daemon=True,
        )

        heartbeat_thread.start()

        logger.info("RelayQueue worker started with ID %s", worker_id)

        while not shutdown_event.is_set():
            try:
                with SessionLocal() as recovery_db:
                    recovered = recover_expired_jobs(recovery_db)

                if recovered:
                    logger.warning("Recovered %s expired jobs", recovered)

                if shutdown_event.is_set():
                    break

                processed = process_one_job(worker_id)

                if not processed:
                    shutdown_event.wait(poll_interval)

            except Exception:
                logger.exception("Worker encountered an unexpected error")
                shutdown_event.wait(poll_interval)

    finally:
        logger.info("Worker shutdown requested: %s", worker_id)

        try:
            set_worker_status(worker_id, "draining")
        except Exception:
            logger.exception("Failed to mark worker as draining")

        heartbeat_stop_event.set()

        if "heartbeat_thread" in locals():
            heartbeat_thread.join(timeout=HEARTBEAT_INTERVAL_SECONDS + 2)

            if heartbeat_thread.is_alive():
                logger.error("Heartbeat thread did not stop within the timeout")

        try:
            set_worker_status(worker_id, "offline")
        except Exception:
            logger.exception("Failed to mark worker as offline")

        if metrics_server is not None:
            metrics_server.shutdown()
            metrics_server.server_close()

        if metrics_thread is not None:
            metrics_thread.join(timeout=5)

        for sig, previous_handler in previous_handlers.items():
            signal.signal(sig, previous_handler)

        logger.info("Worker %s stopped successfully", worker_id)


if __name__ == "__main__":
    start_worker()
