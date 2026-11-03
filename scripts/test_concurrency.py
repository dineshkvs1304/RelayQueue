from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from relayqueue.database.connection import SessionLocal
from relayqueue.models.job import Job
from relayqueue.services.worker_registry_service import register_worker
from relayqueue.services.worker_service import (
    claim_next_job,
    complete_job,
)


def main():
    # Register two independent workers.
    with SessionLocal() as db:
        worker_a = register_worker(
            db,
            name="concurrency-worker-A",
            hostname="localhost",
        )
        worker_a_id = worker_a.id

        worker_b = register_worker(
            db,
            name="concurrency-worker-B",
            hostname="localhost",
        )
        worker_b_id = worker_b.id

        # Create two valid jobs.
        job_a = Job(
            task_type="send_email",
            payload={
                "recipient": "test-a@example.com",
                "subject": "Concurrency test A",
            },
            status="pending",
            priority=100,
            max_attempts=3,
        )

        job_b = Job(
            task_type="send_email",
            payload={
                "recipient": "test-b@example.com",
                "subject": "Concurrency test B",
            },
            status="pending",
            priority=100,
            max_attempts=3,
        )

        db.add_all([job_a, job_b])
        db.commit()

        print("Registered workers:")
        print("Worker A:", worker_a_id)
        print("Worker B:", worker_b_id)

        print("\nCreated jobs:")
        print("Job A:", job_a.id)
        print("Job B:", job_b.id)

    # Synchronize both workers so they attempt to claim together.
    barrier = Barrier(2)

    def claim_for_worker(worker_id):
        barrier.wait()

        with SessionLocal() as db:
            return worker_id, claim_next_job(db, worker_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_a = executor.submit(claim_for_worker, worker_a_id)
        future_b = executor.submit(claim_for_worker, worker_b_id)

        result_a = future_a.result()
        result_b = future_b.result()

    claims = [result_a, result_b]

    print("\nConcurrent claim results:")

    successful_claims = []

    for worker_id, claimed in claims:
        if claimed is None:
            print("Worker", worker_id, "did not receive a job")
            continue

        job, attempt = claimed

        print("Worker:", worker_id)
        print("Job:", job.id)
        print("Attempt:", attempt.id)
        print("Recorded owner:", attempt.worker_id)
        print("Status:", job.status)

        successful_claims.append((worker_id, job.id, attempt.id, attempt.worker_id))

    # Validate that both workers claimed different jobs.
    assert len(successful_claims) == 2, "Expected both workers to claim a job"

    claimed_job_ids = [claim[1] for claim in successful_claims]
    assert len(set(claimed_job_ids)) == 2, "Duplicate job claim detected"

    for worker_id, job_id, attempt_id, recorded_owner in successful_claims:
        assert worker_id == recorded_owner, "Attempt worker ownership does not match claimant"

    # Complete both test jobs to leave the database clean.
    for worker_id, job_id, attempt_id, _ in successful_claims:
        with SessionLocal() as db:
            complete_job(db, job_id, attempt_id)

    print("\nSUCCESS: Both workers claimed different jobs.")
    print("SUCCESS: Worker ownership was recorded correctly.")
    print("SUCCESS: Both test jobs were completed.")


if __name__ == "__main__":
    main()
