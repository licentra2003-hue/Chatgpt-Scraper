# Production-Ready Async Scraper API

## Overview

This is a production-ready asynchronous API server for the ChatGPT scraper. It provides:

- **Async job processing** - Submit jobs and get `job_id` immediately
- **Webhook support** - Receive notifications when jobs complete
- **WebSocket updates** - Real-time job status updates
- **Background task processing** - Non-blocking scraping operations
- **Concurrent job handling** - Process multiple jobs simultaneously

## Architecture

### Data Flow

```
Frontend/Client
    ↓ POST /api/scrape
API Server (returns job_id immediately)
    ↓
Job Queue (pending jobs)
    ↓
Background Processor (async task)
    ↓
Browser Manager + Scraper
    ↓
Job Status Update (completed/failed)
    ↓
├─ Webhook Notification (if provided)
└─ WebSocket Broadcast (to connected clients)
```

### Components

#### 1. **Job Queue & State Manager**
- In-memory queue with asyncio (easily replaceable with Redis/RabbitMQ)
- Job states: `pending`, `processing`, `completed`, `failed`
- Job metadata: query, status, result, error, timestamps, webhook_url

#### 2. **Background Task Processor**
- Runs scraping jobs asynchronously
- Updates job status in real-time
- Sends webhooks on completion
- Broadcasts to WebSocket clients

#### 3. **WebSocket Manager**
- Manages active connections
- Broadcasts job updates to connected clients
- Supports multiple concurrent connections per job

#### 4. **API Endpoints**

##### `POST /api/scrape`
Submit a new scraping job.

**Request:**
```json
{
  "query": "What is the best MMP platform?",
  "webhook_url": "https://your-domain.com/webhook"  // Optional
}
```

**Response:**
```json
{
  "job_id": "uuid-here",
  "status": "pending",
  "message": "Job submitted successfully. Use /api/jobs/{job_id} to check status."
}
```

##### `GET /api/jobs/{job_id}`
Get job status and result.

**Response:**
```json
{
  "id": "uuid-here",
  "query": "What is the best MMP platform?",
  "status": "completed",
  "created_at": "2025-01-25T...",
  "completed_at": "2025-01-25T...",
  "result": {
    "query": "What is the best MMP platform?",
    "response_text": "There isn't a single 'best' MMP...",
    "source_links": [...],
    "total_sources": 18,
    "success": true,
    "timestamp": "2025-01-25T..."
  }
}
```

##### `GET /api/jobs`
List all jobs.

##### `WS /ws/jobs/{job_id}`
WebSocket endpoint for real-time job updates.

**Message Format:**
```json
{
  "type": "job_update",
  "job": {
    "id": "uuid-here",
    "status": "processing",
    ...
  }
}
```

## Installation

```bash
pip install fastapi uvicorn httpx websockets aiohttp
```

## Running the Server

```bash
python production_api_server.py
```

Server will start at: `http://localhost:3000`

## Usage Examples

### 1. Submit Job (Basic)

```bash
curl -X POST http://localhost:3000/api/scrape \
  -H "Content-Type: application/json" \
  -d '{"query":"What is the best MMP platform?"}'
```

Response:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "Job submitted successfully..."
}
```

### 2. Check Job Status

```bash
curl http://localhost:3000/api/jobs/{job_id}
```

### 3. Submit Job with Webhook

```bash
curl -X POST http://localhost:3000/api/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is the best MMP platform?",
    "webhook_url": "https://your-domain.com/webhook"
  }'
```

Webhook will receive POST with:
```json
{
  "job_id": "uuid-here",
  "status": "completed",
  "query": "What is the best MMP platform?",
  "result": {...},
  "completed_at": "2025-01-25T..."
}
```

### 4. WebSocket Real-time Updates

```javascript
const ws = new WebSocket('ws://localhost:3000/ws/jobs/{job_id}');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'job_update') {
    console.log('Job status:', data.job.status);
    if (data.job.status === 'completed') {
      console.log('Result:', data.job.result);
    }
  }
};
```

## Testing

### Run All Tests

```bash
# Test 1: Basic async API
python test_production_api.py

# Test 2: WebSocket updates
python test_websocket_updates.py

# Test 3: Webhook functionality
python test_webhook.py
```

### Test Concurrent Jobs

The `test_production_api.py` includes a concurrent job test that submits 5 jobs simultaneously and tracks their completion.

## Production Considerations

### Current Implementation

- **Queue**: In-memory (asyncio.Queue)
- **Job Storage**: In-memory dictionary
- **Concurrency**: Single background processor

### For Scale (1000+ concurrent users)

#### 1. **Replace In-Memory Queue with Redis**
```python
# Install: pip install redis
import redis
redis_client = redis.Redis(host='localhost', port=6379, db=0)
# Use Redis Queue or RQ for job management
```

#### 2. **Use Message Queue (RabbitMQ)**
```python
# Install: pip install aio-pika
# Use existing RabbitMQ setup from worker/main.py
```

#### 3. **Distributed Workers**
```bash
# Run multiple worker instances
python production_api_server.py  # Worker 1
python production_api_server.py  # Worker 2
python production_api_server.py  # Worker 3
```

#### 4. **Database Persistence**
```python
# Store jobs in PostgreSQL/MongoDB
# Use SQLAlchemy or Motor for async DB operations
```

#### 5. **Rate Limiting**
```python
# Install: pip install slowapi
from slowapi import Limiter
limiter = Limiter(key_func=get_remote_address)
```

#### 6. **Authentication**
```python
# Add JWT authentication
# Protect endpoints with API keys
```

## Key Differences: Synchronous vs Asynchronous

### Synchronous (Old `local_api_server.py`)

```python
POST /api/scrape
    ↓
Wait 30-60 seconds...
    ↓
Return result immediately
```

**Pros:**
- Simple, easy to understand
- Immediate result in single request

**Cons:**
- Blocks HTTP connection
- Timeout issues with long jobs
- Poor UX for slow connections
- Doesn't scale well

### Asynchronous (New `production_api_server.py`)

```python
POST /api/scrape
    ↓
Return job_id immediately (100ms)
    ↓
Background processing...
    ↓
Client polls /api/scrapes/{job_id} OR
    receives webhook OR
    listens to WebSocket
```

**Pros:**
- Non-blocking
- Better UX
- Scales to many concurrent users
- Real-time updates via WebSocket
- Webhook notifications

**Cons:**
- Slightly more complex
- Client needs to handle async pattern

## Frontend Integration

### React Example

```javascript
// Submit job
const submitJob = async (query) => {
  const response = await fetch('http://localhost:3000/api/scrape', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query })
  });
  const { job_id } = await response.json();
  return job_id;
};

// Poll for result (simple approach)
const pollForResult = async (jobId) => {
  while (true) {
    const response = await fetch(`http://localhost:3000/api/jobs/${jobId}`);
    const job = await response.json();
    
    if (job.status === 'completed') {
      return job.result;
    } else if (job.status === 'failed') {
      throw new Error(job.error);
    }
    
    await new Promise(r => setTimeout(r, 2000));
  }
};

// WebSocket approach (better UX)
const watchJob = (jobId, onUpdate) => {
  const ws = new WebSocket(`ws://localhost:3000/ws/jobs/${jobId}`);
  
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'job_update') {
      onUpdate(data.job);
    }
  };
  
  return ws;
};
```

## Monitoring & Logging

### Current Logging

The server logs:
- Job submissions
- Status changes
- Completion/failure
- Webhook sends
- WebSocket connections

### For Production

Add:
- Structured logging (JSON format)
- Log aggregation (ELK stack)
- Metrics (Prometheus)
- Tracing (Jaeger/Zipkin)
- Error tracking (Sentry)

## Security

### Current State

- No authentication
- No rate limiting
- No input validation beyond Pydantic

### Recommended for Production

1. **API Key Authentication**
```python
from fastapi.security import APIKeyHeader
api_key_header = APIKeyHeader(name="X-API-Key")
```

2. **Rate Limiting**
```python
from slowapi import Limiter
limiter = Limiter(key_func=get_remote_address)
```

3. **Input Sanitization**
```python
# Validate query length, format
# Sanitize HTML in responses
```

4. **CORS Configuration**
```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["https://yourdomain.com"])
```

## Troubleshooting

### Jobs stuck in "pending"

- Check background processor is running
- Check browser manager initialization
- Check logs for errors

### WebSocket connection fails

- Ensure job_id is valid
- Check firewall settings
- Verify WebSocket support in client

### Webhook not received

- Verify webhook URL is accessible
- Check server can reach webhook URL
- Check webhook server logs

## Performance

### Benchmarks (approximate)

- **Job submission**: ~100ms (immediate response)
- **Scraping time**: 30-60 seconds (depends on query)
- **Concurrent jobs**: 5-10 jobs simultaneously (single worker)
- **WebSocket latency**: <50ms

### Optimization Tips

1. Increase worker processes
2. Use Redis for queue
3. Add caching for common queries
4. Optimize browser launch time (reuse profiles)
5. Implement request batching

## License

Same as parent project.

## Support

For issues or questions, refer to the main project documentation.
