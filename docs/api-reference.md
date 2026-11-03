# RelayQueue — API Reference

## 1. Overview

RelayQueue exposes a REST API built with FastAPI.

The API allows clients to submit and inspect jobs, cancel pending jobs, inspect execution history, retry dead-letter jobs, and register workers.

**Base URL:** `http://localhost:8000`

**Interactive API documentation:** `http://localhost:8000/docs`

**OpenAPI schema:** `http://localhost:8000/openapi.json`

## 2. Health and Monitoring Endpoints

### GET /health

Checks application and database connectivity.

Successful response — HTTP 200:

```json
{
  "status": "healthy",
  "database": "connected"
}
```

Database connectivity failure returns HTTP 503.

### GET /metrics

Exposes Prometheus metrics for scraping.

Metrics include:

- Jobs processed by status.
- Job failures.
- Job retries.
- Job execution duration.
- Worker status.
- Active jobs.

## 3. Job Endpoints

### POST /jobs

Creates a new background job.

**Request body:**

```json
{
  "task_type": "echo",
  "payload": {
    "message": "Hello RelayQueue"
  },
  "priority": 5,
  "max_attempts": 3
}
```

An optional `scheduled_at` field specifies a future timezone-aware execution time.

**Request validation:**

| Field | Default | Constraints |
|---|---|---|
| task_type | Required | 1–100 characters |
| payload | Empty object | JSON object |
| priority | 0 | 0–100 |
| max_attempts | 3 | 1–10 |
| scheduled_at | None | Must be timezone-aware and in the future |

**Optional header:**

`Idempotency-Key: unique-request-identifier`

The header must contain between 1 and 255 characters.

**Responses:**

| Status | Meaning |
|---|---|
| 201 | Job created |
| 200 | Existing matching idempotent request returned |
| 409 | Idempotency key reused with different request content |
| 422 | Request validation failed |

### GET /jobs

Lists jobs with pagination and optional status filtering.

**Query parameters:**

| Parameter | Default | Constraints |
|---|---:|---|
| page | 1 | Minimum 1 |
| page_size | 20 | 1–100 |
| status | None | Optional status filter |

Supported status values:

- `pending`
- `running`
- `completed`
- `retrying`
- `failed`
- `dead_letter`
- `cancelled`

Example:

`GET /jobs?page=1&page_size=10&status=pending`

**Response structure:**

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 10
}
```

### GET /jobs/dead-letter

Lists jobs currently in the dead-letter state.

Supports pagination using `page` and `page_size`, with defaults of 1 and 20 respectively. The maximum page size is 100.

Returns a paginated response containing `items`, `total`, `page`, and `page_size`.

### GET /jobs/{job_id}

Retrieves a job by its UUID.

The job response includes:

- `id`
- `task_type`
- `payload`
- `idempotency_key`
- `status`
- `priority`
- `attempts`
- `max_attempts`
- `available_at`
- `created_at`
- `updated_at`

**Responses:**

| Status | Meaning |
|---|---|
| 200 | Job found |
| 404 | Job not found |
| 422 | Invalid UUID |

### DELETE /jobs/{job_id}

Cancels a pending job.

**Responses:**

| Status | Meaning |
|---|---|
| 200 | Job cancelled |
| 404 | Job not found |
| 409 | Job cannot be cancelled in its current state |
| 422 | Invalid UUID |

### GET /jobs/{job_id}/attempts

Retrieves execution-attempt history for a job.

Each attempt response contains:

- `id`
- `job_id`
- `worker_id`
- `attempt_number`
- `status`
- `started_at`
- `finished_at`
- `error_message`
- `result`

Returns HTTP 404 if the job does not exist.

### POST /jobs/{job_id}/retry

Manually retries a dead-letter job.

The service resets the job to pending and updates its attempt allowance according to the current retry policy.

**Responses:**

| Status | Meaning |
|---|---|
| 200 | Job successfully reset for retry |
| 404 | Job not found |
| 409 | Job cannot be manually retried in its current state |
| 422 | Invalid UUID |

## 4. Worker Endpoints

### POST /workers

Registers a new worker.

**Request body:**

```json
{
  "name": "relay-worker-01",
  "hostname": "localhost"
}
```

**Validation:**

| Field | Constraints |
|---|---|
| name | 1–100 characters |
| hostname | 1–255 characters |

**Response:** HTTP 201 on successful registration.

The response includes worker ID, name, hostname, status, last heartbeat, and start time.

### POST /workers/{worker_id}/heartbeat

Records a heartbeat for a registered worker.

**Responses:**

| Status | Meaning |
|---|---|
| 200 | Heartbeat recorded |
| 404 | Worker not found |
| 409 | Worker heartbeat rejected because of an invalid state |
| 422 | Invalid worker UUID |

## 5. Request Correlation

The API accepts an optional `X-Request-ID` header.

If the client does not provide one, the middleware generates a request ID.

The response includes the resulting `X-Request-ID` header.

This identifier is also included in structured request logs.

## 6. Error Handling

RelayQueue uses HTTP status codes to indicate request outcomes.

| HTTP status | Meaning |
|---|---|
| 200 | Successful request |
| 201 | Resource created |
| 404 | Resource not found |
| 409 | Conflict with current resource state or idempotency key |
| 422 | Request validation failure |
| 503 | Database health check failure |

Error response bodies follow FastAPI's response behavior and the application's configured exception handling.

## 7. Example Workflow

The following example demonstrates submitting a job and checking its status.

### Step 1: Submit a job

```powershell
$body = @{
    task_type = "echo"
    payload = @{
        message = "Hello RelayQueue"
    }
    priority = 5
    max_attempts = 3
} | ConvertTo-Json -Depth 5

$response = Invoke-RestMethod `
    -Method Post `
    -Uri "http://localhost:8000/jobs" `
    -ContentType "application/json" `
    -Body $body

$response
```

### Step 2: Retrieve the job

```powershell
$jobId = $response.id

Invoke-RestMethod `
    -Uri "http://localhost:8000/jobs/$jobId"
```

### Step 3: Inspect execution attempts

```powershell
Invoke-RestMethod `
    -Uri "http://localhost:8000/jobs/$jobId/attempts"
```

### Step 4: Inspect dead-letter jobs

```powershell
Invoke-RestMethod `
    -Uri "http://localhost:8000/jobs/dead-letter"
```

## 8. Interactive API Documentation

FastAPI provides an interactive Swagger UI.

Open:

`http://localhost:8000/docs`

The interface allows developers to:

- Inspect available endpoints.
- Review request schemas.
- Submit test requests.
- Inspect response bodies and status codes.
- Explore the generated API schema.

## 9. Notes

- Job execution is performed by worker processes, not directly by the API request.
- Job availability depends on `available_at`.
- Only pending jobs can be cancelled through the current cancellation endpoint.
- Dead-letter jobs can be manually retried.
- The API does not promise exactly-once execution of external task side effects.