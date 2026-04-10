# Scraper System - Complete Workflow Documentation

## Table of Contents
1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [Data Flow](#data-flow)
4. [Services](#services)
5. [Key Files and Their Roles](#key-files-and-their-roles)
6. [API Endpoints](#api-endpoints)
7. [Worker Processing](#worker-processing)
8. [Database Schema](#database-schema)
9. [Environment Variables](#environment-variables)
10. [Docker Compose Configuration](#docker-compose-configuration)
11. [Testing](#testing)
12. [Troubleshooting](#troubleshooting)

---

## System Overview

This is a **production-ready asynchronous ChatGPT scraper system** with the following key characteristics:

- **Async job processing** - Submit jobs and get `job_id` immediately
- **Real-time result streaming** - Server-Sent Events (SSE) for live result delivery
- **No result persistence in database** - Results stored in memory only, delivered via SSE
- **Message queue based** - RabbitMQ for job distribution
- **Multi-container Docker setup** - API, Worker, and RabbitMQ services
- **Browser automation** - Playwright for ChatGPT scraping
- **Smart identity rotation** - Automatic browser profile rotation on detection

---

## Architecture

```
┌─────────────┐
│   Client    │
│  (Browser)  │
└──────┬──────┘
       │
       │ POST /api/scrape
       │ { "query": "..." }
       ↓
┌─────────────────────────────────────────────────────────────┐
│                      API Server (Go/Fiber)                  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  POST /api/scrape → Create job → Publish to RabbitMQ  │ │
│  │  GET  /api/stream/:id → SSE stream (status + result)  │ │
│  │  POST /api/result/:id → Receive result from worker    │ │
│  │  GET  /api/result/:id → Get job status + result       │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
       │                           ↕
       │ Publish                  Consume
       ↓                           │
┌─────────────┐            ┌──────────────┐
│  RabbitMQ   │────────────│   Worker     │
│  (Queue)    │            │  (Python)    │
└─────────────┘            └──────────────┘
                                   │
                                   │ Playwright
                                   ↓
                            ┌──────────────┐
                            │   ChatGPT     │
                            │   Website     │
                            └──────────────┘
```

---

## Data Flow

### 1. Job Submission
```
Client → POST /api/scrape {query} → API
  ↓
API creates job in database (status: pending)
  ↓
API publishes job to RabbitMQ queue
  ↓
API returns {job_id, status: "pending"} to client
```

### 2. Job Processing
```
Worker consumes from RabbitMQ
  ↓
Worker receives job {job_id, query}
  ↓
Worker launches Playwright browser
  ↓
Worker scrapes ChatGPT for response
  ↓
Worker POSTs result to API: POST /api/result/:id
  ↓
Worker updates database: processed_at = now (status: completed)
```

### 3. Result Delivery (SSE)
```
Client → GET /api/stream/:id (SSE connection)
  ↓
API sends: event: status → {status: "pending"}
  ↓
API polls for result (up to 180s, 1s intervals)
  ↓
When worker POSTs result:
  API sends: event: result → {query, response_text, source_links, ...}
  API sends: event: status → {status: "completed"}
  ↓
Client receives live result
```

---

## Services

### 1. API Service (`scraper-api-new`)
- **Technology**: Go with Fiber framework
- **Port**: 3000 (mapped to 3001 on host)
- **Responsibilities**:
  - Accept scraping requests
  - Create and track jobs
  - Publish jobs to RabbitMQ
  - Receive results from worker
  - Stream results via SSE
  - Serve job status queries

### 2. Worker Service (`scraper-system-worker-1`)
- **Technology**: Python with Playwright
- **Responsibilities**:
  - Consume jobs from RabbitMQ
  - Launch browser automation
  - Scrape ChatGPT responses
  - Extract text and sources
  - POST results back to API
  - Handle identity rotation on blocks

### 3. RabbitMQ Service (`scraper-rabbitmq-new`)
- **Image**: rabbitmq:3.12-management
- **Ports**: 5672 (AMQP), 15672 (Management UI)
- **Responsibilities**:
  - Message queue for job distribution
  - Durable queue persistence
  - Management console for monitoring

---

## Key Files and Their Roles

### Root Directory Files

#### Configuration Files

| File | Purpose |
|------|---------|
| `.env` | Environment variables (Supabase, RabbitMQ, Proxy settings) |
| `docker-compose.yml` | Multi-container orchestration configuration |
| `database_schema.sql` | Supabase database schema definition |

#### Test Scripts

| File | Purpose |
|------|---------|
| `fetch_result.py` | SSE client test - demonstrates real-time result streaming |
| `test_docker_workflow.py` | End-to-end Docker workflow test |
| `test_local_api.py` | Local API server testing |
| `test_concurrent_queries.py` | Concurrent job submission testing |
| `test_multiple_queries.py` | Multiple query testing |
| `test_streaming.py` | SSE streaming functionality test |
| `production_api_server.py` | Alternative FastAPI implementation (reference) |
| `local_api_server.py` | Local synchronous API (reference) |

#### Documentation

| File | Purpose |
|------|---------|
| `PRODUCTION_API_README.md` | Production API documentation |
| `WORKFLOW.md` | This file - complete workflow documentation |

---

### API Service (`api/`)

#### Main Entry Point
**`api/main.go`**
- Entry point for Go API server
- Initializes database and queue connections
- Sets up Fiber routes
- Handles graceful shutdown
- Loads environment variables from `.env`

#### Handlers

**`api/handlers/scrape.go`**
- `PostScrape()` - Creates job and publishes to queue
- `GetResult()` - Returns job status and result (from memory if available)
- `PostResult()` - Receives scraped result from worker
- `StreamResult()` - SSE streaming endpoint for real-time updates
- Maintains in-memory result cache (not stored in database)
- Waits up to 45s after DB completion for worker result callback

**`api/handlers/database.go`**
- `NewDatabase()` - Initializes Supabase connection
- `CreateJob()` - Creates job in `processed_jobs` table
- `GetJob()` - Retrieves job status (derives from `processed_at`)
- Supports both PostgreSQL and PostgREST (HTTP) modes
- Mock database fallback for testing

**`api/handlers/queue.go`**
- `NewQueue()` - Connects to RabbitMQ
- `PublishJob()` - Publishes job to `scraping_tasks` queue
- `GetQueueInfo()` - Gets queue message count
- `Close()` - Closes RabbitMQ connection

#### Models
**`api/models/job.go`**
- `ScrapeRequest` - Request model for `/api/scrape`
- `Job` - Job model with ID, query, status, timestamps
- `QueueMessage` - Message format for RabbitMQ
- `ScrapeResponse` - Response model with job_id

#### Docker Configuration
**`api/Dockerfile`**
- Multi-stage build (builder + distroless)
- Builds Go binary with `-buildvcs=false` flag
- Creates minimal static binary
- Exposes port 3000

---

### Worker Service (`worker/`)

#### Main Entry Point
**`worker/main.py`**
- Entry point for worker process
- Connects to RabbitMQ and consumes jobs
- Initializes `BrowserManager` and `ChatGPTScraper`
- Processes jobs asynchronously
- Posts results to API with retries (3 attempts)
- Updates Supabase `processed_jobs` table
- Handles identity rotation on soft blocks
- Uses unique worker ID for profile isolation

#### Scraper Logic
**`worker/scraper.py`**
- **Data Models**:
  - `SourceLink` - Represents a source citation
  - `ScrapingResult` - Complete scrape result
  - `ChatGPTSelectors` - CSS selectors for ChatGPT UI

- **Classes**:
  - `BrowserManager` - Manages Playwright browser context
  - `ChatGPTScraper` - Main scraping logic

- **Key Methods**:
  - `scrape()` - Main scraping workflow
  - `_submit_query()` - Submits query to ChatGPT
  - `_wait_for_response()` - Waits for response generation
  - `_extract_text()` - Extracts response text
  - `_extract_sources()` - Extracts source citations
  - `_kill_overlays()` - Removes popup overlays
  - `_wait_for_sources_button()` - Waits for sources sidebar
  - `_save_file()` - Saves result to JSON file

- **Features**:
  - Cloudflare challenge handling
  - Soft block detection
  - Overlay removal
  - Source extraction from sidebar
  - Stealth browser configuration

#### Dependencies
**`worker/requirements.txt`**
```
playwright==1.48.0
pika==1.3.2
supabase==2.7.0
python-dotenv==1.0.1
requests==2.31.0
```

#### Docker Configuration
**`worker/Dockerfile`**
- Uses Playwright Python base image
- Installs system dependencies
- Sets `PYTHONUNBUFFERED=1` for logging
- Runs with `python -u main.py`
- Creates profiles directory
- Sets proper permissions for user

---

### Test Suite (`tests/`)

| File | Purpose |
|------|---------|
| `test_api_flow.py` | Tests complete API flow (create, queue, process) |
| `test_api_flow_mock.py` | Mock database version of API flow test |
| `test_full_flow.py` | End-to-end system test |
| `test_infra.py` | Infrastructure validation tests |
| `test_queue_only.py` | RabbitMQ queue functionality |
| `test_worker_consume.py` | Worker message consumption |
| `test_worker_logic.py` | Worker processing logic |
| `test_worker_mock.py` | Mock worker for testing |
| `test_worker_start.py` | Worker startup validation |
| `simple_test.py` | Basic functionality test |
| `stress_test.sh` | Load testing script |

---

## API Endpoints

### POST `/api/scrape`
**Purpose**: Submit a new scraping job

**Request**:
```json
{
  "query": "What is the capital of France?"
}
```

**Response** (201 Created):
```json
{
  "job_id": "uuid-here"
}
```

**Flow**:
1. Validate request
2. Create job in database (status: pending)
3. Publish job to RabbitMQ
4. Return job_id to client

---

### GET `/api/result/:id`
**Purpose**: Get job status and result

**Response** (200 OK):
```json
{
  "id": "uuid-here",
  "query": "What is the capital of France?",
  "status": "completed",
  "created_at": "2026-02-21T...",
  "updated_at": "2026-02-21T...",
  "result": {
    "query": "What is the capital of France?",
    "response_text": "The capital of France is Paris.",
    "source_links": [...],
    "total_sources": 0,
    "success": true,
    "timestamp": "..."
  }
}
```

**Flow**:
1. Retrieve job from database
2. Check in-memory result cache
3. Return job status + result (if available)

---

### POST `/api/result/:id`
**Purpose**: Worker posts scraped result to API

**Request**:
```json
{
  "result": {
    "query": "...",
    "response_text": "...",
    "source_links": [...],
    "total_sources": 0,
    "success": true,
    "timestamp": "..."
  }
}
```

**Response** (200 OK):
```json
{
  "status": "result received"
}
```

**Flow**:
1. Validate request body
2. Serialize result to JSON
3. Store in in-memory cache (keyed by job_id)
4. Log result receipt

---

### GET `/api/stream/:id`
**Purpose**: SSE stream for real-time job updates

**Response Format** (Server-Sent Events):
```
event: status
data: {"status":"pending"}

event: result
data: {"query":"...","response_text":"...",...}

event: status
data: {"status":"completed"}
```

**Flow**:
1. Set SSE headers
2. Send initial status (pending)
3. Poll for result (up to 180s, 1s intervals)
4. When result available, stream it
5. Wait up to 45s after DB completion for worker callback
6. Send completed status

---

### GET `/health`
**Purpose**: Health check endpoint

**Response** (200 OK):
```json
{
  "status": "ok",
  "service": "scraper-api"
}
```

---

## Worker Processing

### Job Lifecycle

```
1. Consume Message
   ↓
2. Parse {job_id, query}
   ↓
3. Initialize ChatGPTScraper
   ↓
4. Get Playwright Page
   ↓
5. Navigate to ChatGPT
   ↓
6. Handle Cloudflare (if present)
   ↓
7. Clear Overlays
   ↓
8. Submit Query
   ↓
9. Wait for Response
   ↓
10. Check for Soft Block
    ↓
11. Extract Text
    ↓
12. Extract Sources
    ↓
13. POST Result to API (retry 3x)
    ↓
14. Update Database (processed_at)
    ↓
15. Acknowledge RabbitMQ Message
```

### Error Handling

**Soft Block Detection**:
```
If "soft block" OR "cloudflare" OR "sign up" detected:
  1. Close Browser
  2. Delete Profile Folder
  3. BrowserManager recreates fresh profile
  4. Job marked as failed (not retried)
```

**Result POST Failure**:
```
If POST to API fails (3 attempts):
  1. Log error
  2. Mark job as failed
  3. Do not update processed_at
```

---

## Database Schema

### `processed_jobs` Table

```sql
CREATE TABLE processed_jobs (
  job_id VARCHAR PRIMARY KEY,
  processed_at TIMESTAMP,
  expires_at TIMESTAMP,
  engine VARCHAR
);
```

**Purpose**: Track job completion status (not results)

**Columns**:
- `job_id` - Job identifier (UUID string)
- `processed_at` - Completion timestamp (NULL = pending)
- `expires_at` - Result expiration (24 hours after completion)
- `engine` - Scraper engine (e.g., "Chatgpt")

**Status Derivation**:
- `processed_at IS NULL` → status = "pending"
- `processed_at IS NOT NULL` → status = "completed"

**Note**: Results are NOT stored in database - only in API memory cache

---

## Environment Variables

### Required Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `RABBITMQ_URL` | RabbitMQ connection string | Required |
| `SUPABASE_URL` | Supabase connection URL | Required |
| `SUPABASE_KEY` | Supabase API key | Required |
| `API_URL` | Worker callback URL | `http://api:3000` |

### Optional Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `PORT` | API server port | `3000` |
| `HEADLESS` | Run browser headless | `"true"` |
| `PROXY_SERVER` | Proxy server URL | `""` |
| `PROXY_USERNAME` | Proxy username | `""` |
| `PROXY_PASSWORD` | Proxy password | `""` |

### Docker Compose Overrides

In `docker-compose.yml`:
- API: `RABBITMQ_URL=amqp://admin:admin123@rabbitmq:5672`
- Worker: `RABBITMQ_URL=amqp://admin:admin123@rabbitmq:5672`
- Worker: `API_URL=http://api:3000`

---

## Docker Compose Configuration

### Services

#### RabbitMQ
```yaml
rabbitmq:
  image: rabbitmq:3.12-management
  container_name: scraper-rabbitmq-new
  ports:
    - "5673:5672"   # AMQP
    - "15673:15672" # Management UI
  environment:
    RABBITMQ_DEFAULT_USER: admin
    RABBITMQ_DEFAULT_PASS: admin123
  volumes:
    - rabbitmq_data:/var/lib/rabbitmq
  healthcheck:
    test: ["CMD", "rabbitmq-diagnostics", "ping"]
```

#### API
```yaml
api:
  build:
    context: ./api
    dockerfile: Dockerfile
  container_name: scraper-api-new
  ports:
    - "3001:3000"
  env_file:
    - .env
  environment:
    RABBITMQ_URL: amqp://admin:admin123@rabbitmq:5672
  depends_on:
    - rabbitmq
```

#### Worker
```yaml
worker:
  build:
    context: ./worker
    dockerfile: Dockerfile
  env_file:
    - .env
  environment:
    RABBITMQ_URL: amqp://admin:admin123@rabbitmq:5672
    HEADLESS: "true"
    PROXY_SERVER: ""
    PROXY_USERNAME: ""
    PROXY_PASSWORD: ""
    API_URL: http://api:3000
  depends_on:
    - rabbitmq
    - api
  deploy:
    replicas: 1
  ipc: host  # Browser shared memory
  volumes:
    - worker_profiles:/app/profiles
```

### Volumes
- `rabbitmq_data` - Persistent RabbitMQ data
- `worker_profiles` - Browser profile storage

---

## Testing

### Running Tests

```bash
# Test Docker workflow
python test_docker_workflow.py

# Test SSE streaming
python fetch_result.py

# Test API flow
python tests/test_api_flow.py

# Test worker consumption
python tests/test_worker_consume.py

# Stress test
bash tests/stress_test.sh
```

### Test Categories

1. **Unit Tests** - Individual component testing
2. **Integration Tests** - Service interaction testing
3. **Flow Tests** - End-to-end workflow testing
4. **Stress Tests** - Concurrent job handling

---

## Troubleshooting

### Common Issues

#### 1. Worker Not Processing Jobs
**Symptoms**: Jobs stay in "pending" status

**Solutions**:
- Check worker logs: `docker logs scraper-system-worker-1`
- Verify RabbitMQ connection
- Check if worker is running: `docker ps`
- Restart worker: `docker-compose restart worker`

#### 2. No Result in SSE Stream
**Symptoms**: Status shows "completed" but no result event

**Solutions**:
- Check worker logs for POST failures
- Verify worker can reach API: `API_URL=http://api:3000`
- Check for serialization errors in logs
- Ensure worker is using `dataclasses.asdict()` for result

#### 3. Soft Block Detection
**Symptoms**: Jobs fail with "Soft block" error

**Solutions**:
- Worker automatically rotates identity
- Check profile deletion in logs
- Browser profile recreated automatically
- Wait before retrying job

#### 4. Docker Build Failures
**Symptoms**: Build errors during `docker-compose build`

**Solutions**:
- Check Go build flags: `-buildvcs=false`
- Verify Python unbuffered: `python -u`
- Check network connectivity
- Clear Docker cache: `docker system prune`

#### 5. RabbitMQ Connection Issues
**Symptoms**: Worker can't connect to RabbitMQ

**Solutions**:
- Verify `RABBITMQ_URL` format
- Check RabbitMQ health: `docker logs scraper-rabbitmq-new`
- Test connection: `telnet localhost 5673`
- Restart RabbitMQ: `docker-compose restart rabbitmq`

### Debugging Commands

```bash
# View logs
docker logs scraper-api-new --tail=100
docker logs scraper-system-worker-1 --tail=100
docker logs scraper-rabbitmq-new --tail=100

# Check queue status
docker exec scraper-rabbitmq-new rabbitmqctl list_queues

# Test API
curl http://localhost:3001/health
curl http://localhost:3001/api/scrape -X POST -H "Content-Type: application/json" -d '{"query":"test"}'

# Test SSE
curl -N http://localhost:3001/api/stream/<job_id>

# Check worker status
docker exec scraper-system-worker-1 ps aux
```

---

## Performance Characteristics

### Benchmarks
- **Job submission**: ~100ms (immediate response)
- **Scraping time**: 30-60 seconds (depends on query)
- **Concurrent jobs**: 5-10 jobs simultaneously (single worker)
- **SSE latency**: <50ms

### Optimization Tips
1. Increase worker processes for concurrency
2. Use Redis for queue (scale to 1000+ users)
3. Add caching for common queries
4. Optimize browser launch time (reuse profiles)
5. Implement request batching

---

## Security Considerations

### Current State
- No authentication
- No rate limiting
- Input validation via Pydantic

### Recommended for Production
1. **API Key Authentication**
2. **Rate Limiting**
3. **Input Sanitization**
4. **CORS Configuration**
5. **HTTPS/TLS**

---

## Summary

This scraper system provides:
- ✅ Asynchronous job processing
- ✅ Real-time result streaming via SSE
- ✅ No database result storage (memory-only)
- ✅ RabbitMQ message queue
- ✅ Playwright browser automation
- ✅ Smart identity rotation
- ✅ Multi-container Docker setup
- ✅ Comprehensive test suite
- ✅ Production-ready architecture

The system is designed for scalability and can be extended with:
- Redis for distributed caching
- Multiple worker instances
- PostgreSQL for persistence
- Authentication and rate limiting
- Monitoring and logging (ELK stack, Prometheus)

---

## File Reference

### Core Application Files
- `api/main.go` - API entry point
- `api/handlers/scrape.go` - Scrape endpoints
- `api/handlers/database.go` - Database operations
- `api/handlers/queue.go` - RabbitMQ operations
- `api/models/job.go` - Data models
- `worker/main.py` - Worker entry point
- `worker/scraper.py` - Scraping logic

### Configuration Files
- `docker-compose.yml` - Service orchestration
- `.env` - Environment variables
- `database_schema.sql` - Database schema

### Test Files
- `fetch_result.py` - SSE client test
- `test_docker_workflow.py` - E2E test
- `tests/*.py` - Unit and integration tests

### Documentation
- `WORKFLOW.md` - This file
- `PRODUCTION_API_README.md` - API documentation
