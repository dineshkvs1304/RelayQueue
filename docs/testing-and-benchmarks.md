# RelayQueue — Testing and Performance Benchmarks

## 1. Overview

RelayQueue includes automated tests for its API, database operations, worker lifecycle, job execution, and concurrent job claiming.

The project uses:

- pytest for automated testing.
- PostgreSQL for database integration tests.
- FastAPI TestClient and HTTPX for API testing.
- GitHub Actions for continuous integration.
- Ruff for linting and formatting checks.
- Alembic for database migration validation.

The objective is to validate application behavior, database consistency, and important reliability mechanisms.

## 2. Testing Environment

The local development environment uses:

| Component | Technology |
|---|---|
| Language | Python 3.14 |
| API framework | FastAPI |
| Database | PostgreSQL 18 |
| ORM | SQLAlchemy |
| Migration tool | Alembic |
| Test framework | pytest |
| HTTP testing | HTTPX |
| Linting | Ruff |

Automated tests use a separate PostgreSQL database named `relayqueue_test`.

This keeps test data separate from the development database.

## 3. Test Suite Organization

| Test file | Tests | Main coverage |
|---|---:|---|
| `test_database.py` | 2 | Database connectivity and database behavior |
| `test_jobs.py` | 22 | Job API, creation, validation, cancellation, idempotency and job lifecycle |
| `test_workers.py` | 9 | Worker job processing and execution behavior |
| `test_worker_lifecycle.py` | 13 | Worker lifecycle, lease handling and recovery |
| `test_worker_registry.py` | 4 | Worker registration and heartbeat behavior |
| `test_concurrency.py` | 1 | Concurrent job claiming |
| **Total** | **51** | |

## 4. Running Tests

Activate the virtual environment and run:

```powershell
pytest
```

For verbose output:

```powershell
pytest -v
```

To run an individual test file:

```powershell
pytest tests/test_jobs.py -v
```

To run the concurrency test:

```powershell
pytest tests/test_concurrency.py -v
```

## 5. Verified Test Results

The local test suite previously completed successfully:

```text
51 passed, 1 warning
```

The warning was a Starlette deprecation warning concerning the HTTPX integration with `starlette.testclient`. It did not cause test failures.

The project also passed its GitHub Actions CI pipeline, including migration validation and automated tests against a fresh PostgreSQL service.

## 6. Concurrency Testing

RelayQueue includes a PostgreSQL-backed concurrency test.

Test configuration:

| Parameter | Value |
|---|---:|
| Worker threads | 5 |
| Registered workers | 5 |
| Submitted jobs | 20 |

The test verifies:

- Jobs are not claimed more than once in the tested scenario.
- Each execution attempt has a unique attempt number for its job.
- Claims are associated with the correct worker.
- Concurrent claims maintain consistent database state.

This provides integration-level validation of the PostgreSQL locking approach.

It is not a formal proof of correctness under every possible production concurrency pattern.

## 7. Crash-Recovery Testing

The crash-recovery test simulates an interrupted worker by making a running job's lease expire.

The test verifies:

1. Expired lease detection.
2. Failure recording for the unfinished attempt.
3. Recovery of the job.
4. Claiming by another worker.
5. Creation of a subsequent attempt.
6. Successful completion.

This validates lease-based recovery at the database and service level.

The test simulates lease expiration rather than forcibly terminating a real worker operating-system process.

## 8. Local Performance Benchmark

RelayQueue was tested with multiple worker processes using echo jobs.

### 500-Job Benchmark

| Measurement | Observed result |
|---|---:|
| Jobs submitted | 500 |
| Jobs completed | 500 |
| Submission time | 5.45 seconds |
| Observed processing interval | 3.84 seconds |
| Observed throughput | 130.32 jobs/second |

<text id="metric-note">The observed throughput was calculated as 500 completed jobs divided by the measured processing interval of 3.84 seconds.</text>

### 100-Job Benchmark

| Measurement | Observed result |
|---|---:|
| Jobs submitted | 100 |
| Jobs completed | 100 |
| Submission time | 1.44 seconds |
| Observed processing interval | 1.05 seconds |
| Observed throughput | 94.89 jobs/second |

## 9. Benchmark Methodology and Limitations

These measurements are local development observations, not controlled production benchmarks.

The processing interval was measured after job submission. API polling and the two-second polling interval also affect the observed completion timing.

Results depend on:

- Laptop hardware.
- PostgreSQL configuration.
- Number of worker processes.
- Task-handler execution time.
- Database connection overhead.
- API polling frequency.
- Operating-system scheduling.

The results should not be interpreted as a guaranteed production throughput or a standardized comparison against other job queue systems.

## 10. Continuous Integration

RelayQueue uses GitHub Actions for automated validation.

The CI workflow includes:

1. Checking out the repository.
2. Setting up Python.
3. Starting a PostgreSQL service.
4. Installing project dependencies.
5. Checking Ruff formatting.
6. Running Ruff lint checks.
7. Applying Alembic migrations.
8. Checking migration consistency.
9. Running pytest.

The workflow validates the migration chain and application tests against a fresh PostgreSQL database.

The GitHub Actions pipeline has previously completed successfully.

## 11. Code Quality and Migration Checks

Run Ruff formatting validation:

```powershell
ruff format --check .
```

Run Ruff linting:

```powershell
ruff check .
```

Check Alembic migration consistency:

```powershell
alembic check
```

Apply database migrations:

```powershell
alembic upgrade head
```

Run the complete test suite:

```powershell
pytest
```

## 12. Reliability Coverage

The test suite covers important reliability mechanisms:

| Mechanism | Validation |
|---|---|
| Job creation | API and service tests |
| Idempotent submission | Duplicate and conflicting request tests |
| Job cancellation | Job API tests |
| Worker registration | Worker registry tests |
| Heartbeats | Worker lifecycle tests |
| Job execution | Worker processing tests |
| Lease ownership | Worker lifecycle tests |
| Expired lease recovery | Crash-recovery integration test |
| Concurrent claiming | PostgreSQL concurrency test |
| Database migrations | Alembic and CI validation |

## 13. Future Testing Improvements

Potential improvements include:

- Longer-running concurrency stress tests.
- Repeated randomized worker-failure tests.
- Benchmarks with different worker counts.
- Larger workloads with 1,000 or more jobs.
- Latency percentile measurements such as p50, p95 and p99.
- Database connection-pool stress testing.
- Controlled comparisons across different task-handler workloads.

These are potential future improvements, not currently completed tests.

## 14. Summary

RelayQueue currently has 51 automated tests covering database operations, API behavior, worker processing, worker lifecycle, and concurrent job claiming.

The project has also demonstrated successful local processing of 500 out of 500 submitted jobs and successful GitHub Actions CI validation.

The benchmark results are observational and should be interpreted within their local testing limitations.