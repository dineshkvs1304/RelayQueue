from prometheus_client import Counter, Gauge, Histogram

# Total jobs processed, grouped by final outcome.
JOBS_PROCESSED = Counter(
    "relayqueue_jobs_processed_total",
    "Total number of jobs processed",
    ["status"],
)

# Total job execution failures.
JOB_FAILURES = Counter(
    "relayqueue_job_failures_total",
    "Total number of job execution failures",
)

# Total jobs scheduled for retry.
JOB_RETRIES = Counter(
    "relayqueue_job_retries_total",
    "Total number of jobs scheduled for retry",
)

# Job execution duration in seconds.
JOB_EXECUTION_DURATION = Histogram(
    "relayqueue_job_execution_duration_seconds",
    "Time spent executing jobs",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120),
)

# Number of workers grouped by lifecycle status.
WORKERS = Gauge(
    "relayqueue_workers",
    "Number of registered workers by status",
    ["status"],
)

# Number of jobs currently being executed.
ACTIVE_JOBS = Gauge(
    "relayqueue_active_jobs",
    "Number of jobs currently executing",
)
