from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Lock
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from relayqueue.models.job import Job
from relayqueue.models.job_attempt import JobAttempt
from relayqueue.models.worker import Worker
from relayqueue.services.worker_service import claim_next_job


def test_multiple_workers_claim_jobs_without_duplicates(test_engine):
    """
    Verify that concurrent workers can claim jobs without
    claiming the same job more than once.
    """

    number_of_workers = 5
    number_of_jobs = 20

    worker_ids = []
    job_ids = []
    claimed_records = []

    records_lock = Lock()
    start_barrier = Barrier(number_of_workers)

    try:
        # -------------------------------------------------
        # 1. Create independent workers and pending jobs.
        # -------------------------------------------------

        with Session(test_engine) as db:
            workers = []

            for index in range(number_of_workers):
                worker = Worker(
                    name=f"concurrency-worker-{uuid4().hex}",
                    hostname=f"concurrency-host-{index}",
                    status="active",
                )
                workers.append(worker)

            db.add_all(workers)
            db.flush()

            worker_ids = [worker.id for worker in workers]

            jobs = []

            for index in range(number_of_jobs):
                job = Job(
                    task_type="echo",
                    payload={"message": f"Concurrency test {index}"},
                    status="pending",
                    priority=10,
                    attempts=0,
                    max_attempts=3,
                    available_at=(datetime.now(UTC) - timedelta(seconds=1)),
                )
                jobs.append(job)

            db.add_all(jobs)
            db.flush()

            job_ids = [job.id for job in jobs]

            db.commit()

        # -------------------------------------------------
        # 2. Run multiple workers simultaneously.
        # -------------------------------------------------

        def worker_claim_loop(worker_id):
            local_claims = []

            # Ensure all workers start competing together.
            start_barrier.wait()

            while True:
                with Session(test_engine) as db:
                    claimed = claim_next_job(
                        db,
                        worker_id,
                        lease_duration_seconds=30,
                    )

                if claimed is None:
                    break

                job, attempt = claimed

                local_claims.append(
                    (
                        job.id,
                        attempt.id,
                        worker_id,
                    )
                )

            return local_claims

        with ThreadPoolExecutor(max_workers=number_of_workers) as executor:
            futures = [executor.submit(worker_claim_loop, worker_id) for worker_id in worker_ids]

            for future in futures:
                worker_claims = future.result()

                with records_lock:
                    claimed_records.extend(worker_claims)

        # -------------------------------------------------
        # 3. Verify that every job was claimed exactly once.
        # -------------------------------------------------

        claimed_job_ids = [record[0] for record in claimed_records]

        assert len(claimed_records) == number_of_jobs, (
            f"Expected {number_of_jobs} claims, but received {len(claimed_records)}"
        )

        assert len(set(claimed_job_ids)) == number_of_jobs, "Duplicate job claims detected"

        assert set(claimed_job_ids) == set(job_ids), "Some jobs were not claimed"

        # -------------------------------------------------
        # 4. Verify attempt records and worker ownership.
        # -------------------------------------------------

        with Session(test_engine) as db:
            attempt_counts = db.execute(
                select(
                    JobAttempt.job_id,
                    func.count(JobAttempt.id),
                )
                .where(JobAttempt.job_id.in_(job_ids))
                .group_by(JobAttempt.job_id)
            ).all()

            attempt_count_map = {job_id: count for job_id, count in attempt_counts}

            assert len(attempt_count_map) == number_of_jobs

            assert all(attempt_count_map.get(job_id) == 1 for job_id in job_ids), (
                "Each claimed job must have exactly one attempt"
            )

            for job_id, attempt_id, worker_id in claimed_records:
                job = db.get(Job, job_id)
                attempt = db.get(JobAttempt, attempt_id)

                assert job is not None
                assert attempt is not None

                assert job.status == "running"
                assert job.locked_by == worker_id

                assert attempt.job_id == job_id
                assert attempt.worker_id == worker_id
                assert attempt.status == "running"
                assert attempt.attempt_number == 1

        print("\nCONCURRENCY TEST RESULTS")
        print("------------------------")
        print(f"Workers launched: {number_of_workers}")
        print(f"Jobs created: {number_of_jobs}")
        print(f"Jobs claimed: {len(claimed_records)}")
        print(f"Unique claims: {len(set(claimed_job_ids))}")
        print("Duplicate claims: 0")
        print("Duplicate attempt records: 0")
        print("Worker ownership: verified")
        print("\nCONCURRENCY TEST PASSED")

    finally:
        # -------------------------------------------------
        # 5. Remove committed test records.
        # -------------------------------------------------

        if job_ids or worker_ids:
            with Session(test_engine) as db:
                if job_ids:
                    db.execute(delete(JobAttempt).where(JobAttempt.job_id.in_(job_ids)))

                    db.execute(delete(Job).where(Job.id.in_(job_ids)))

                if worker_ids:
                    db.execute(delete(Worker).where(Worker.id.in_(worker_ids)))

                db.commit()
