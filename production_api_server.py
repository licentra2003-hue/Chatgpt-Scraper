"""
Production-ready asynchronous API server for ChatGPT scraper.
Features:
- Async job processing (returns job_id immediately)
- Webhook support for completion notifications
- WebSocket for real-time updates
- Background task processor
"""

import asyncio
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum

from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, HttpUrl
import uvicorn

from worker.scraper import BrowserManager, ChatGPTScraper, ScrapingResult


# ============== Data Models ==============

class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ScrapeRequest(BaseModel):
    query: str
    webhook_url: Optional[HttpUrl] = None


class JobResult(BaseModel):
    query: str
    response_text: str
    source_links: List[Dict[str, Any]]
    total_sources: int
    success: bool
    timestamp: str
    error_message: Optional[str] = None


class Job(BaseModel):
    id: str
    query: str
    status: JobStatus
    created_at: str
    completed_at: Optional[str] = None
    result: Optional[JobResult] = None
    error: Optional[str] = None
    webhook_url: Optional[str] = None


class JobSubmissionResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str


# ============== WebSocket Manager ==============

class WebSocketManager:
    """Manages WebSocket connections for real-time job updates."""
    
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, job_id: str):
        """Connect a WebSocket client to a specific job."""
        await websocket.accept()
        if job_id not in self.active_connections:
            self.active_connections[job_id] = []
        self.active_connections[job_id].append(websocket)
        print(f"🔌 WebSocket connected for job {job_id}")
    
    def disconnect(self, websocket: WebSocket, job_id: str):
        """Disconnect a WebSocket client."""
        if job_id in self.active_connections:
            self.active_connections[job_id].remove(websocket)
            if not self.active_connections[job_id]:
                del self.active_connections[job_id]
        print(f"🔌 WebSocket disconnected for job {job_id}")
    
    async def broadcast_job_update(self, job_id: str, job: Job):
        """Broadcast job update to all connected clients for this job."""
        if job_id in self.active_connections:
            message = {
                "type": "job_update",
                "job": job.dict()
            }
            disconnected = []
            for connection in self.active_connections[job_id]:
                try:
                    await connection.send_json(message)
                except:
                    disconnected.append(connection)
            
            # Clean up disconnected clients
            for conn in disconnected:
                self.disconnect(conn, job_id)


# ============== Job Queue & Processor ==============

class JobQueue:
    """In-memory job queue and state manager."""
    
    def __init__(self):
        self.jobs: Dict[str, Job] = {}
        self.queue: asyncio.Queue = asyncio.Queue()
        self.processor_task: Optional[asyncio.Task] = None
    
    async def add_job(self, query: str, webhook_url: Optional[str] = None) -> str:
        """Add a new job to the queue and return its ID."""
        job_id = str(uuid.uuid4())
        job = Job(
            id=job_id,
            query=query,
            status=JobStatus.PENDING,
            created_at=datetime.now().isoformat(),
            webhook_url=webhook_url
        )
        self.jobs[job_id] = job
        await self.queue.put(job_id)
        print(f"📋 Job {job_id} added to queue")
        return job_id
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        return self.jobs.get(job_id)
    
    def list_jobs(self) -> List[Job]:
        """List all jobs."""
        return list(self.jobs.values())
    
    async def update_job_status(self, job_id: str, status: JobStatus, 
                               result: Optional[JobResult] = None, 
                               error: Optional[str] = None):
        """Update job status and optionally result/error."""
        if job_id in self.jobs:
            job = self.jobs[job_id]
            job.status = status
            if result:
                job.result = result
            if error:
                job.error = error
            if status in [JobStatus.COMPLETED, JobStatus.FAILED]:
                job.completed_at = datetime.now().isoformat()
            print(f"📊 Job {job_id} status updated to {status}")
    
    async def start_processor(self, browser_manager: BrowserManager, 
                             scraper: ChatGPTScraper, 
                             ws_manager: WebSocketManager):
        """Start the background job processor."""
        async def process_jobs():
            print("🚀 Job processor started")
            while True:
                job_id = await self.queue.get()
                job = self.jobs.get(job_id)
                
                if not job:
                    continue
                
                try:
                    # Update status to processing
                    await self.update_job_status(job_id, JobStatus.PROCESSING)
                    await ws_manager.broadcast_job_update(job_id, job)
                    
                    # Execute scraping
                    print(f"🔨 Processing job {job_id}: {job.query}")
                    page = await browser_manager.start()
                    
                    result = await scraper.scrape(page, job.query)
                    
                    # Update job with result
                    job_result = JobResult(
                        query=result.query,
                        response_text=result.response_text,
                        source_links=[
                            {
                                "text": link.text,
                                "url": link.url,
                                "title": link.title,
                                "description": link.description
                            } for link in result.source_links
                        ],
                        total_sources=result.total_sources,
                        success=result.success,
                        timestamp=result.timestamp,
                        error_message=result.error_message
                    )
                    
                    await self.update_job_status(
                        job_id, 
                        JobStatus.COMPLETED if result.success else JobStatus.FAILED,
                        result=job_result,
                        error=result.error_message
                    )
                    
                    print(f"✅ Job {job_id} completed successfully")
                    
                except Exception as e:
                    await self.update_job_status(
                        job_id, 
                        JobStatus.FAILED, 
                        error=str(e)
                    )
                    print(f"❌ Job {job_id} failed: {e}")
                
                finally:
                    # Broadcast final update
                    await ws_manager.broadcast_job_update(job_id, self.jobs[job_id])
                    
                    # Send webhook if provided
                    job = self.jobs[job_id]
                    if job.webhook_url and job.status in [JobStatus.COMPLETED, JobStatus.FAILED]:
                        await self.send_webhook(job.webhook_url, job)
                    
                    # Clean up browser
                    try:
                        await browser_manager.stop()
                    except:
                        pass
                    
                    self.queue.task_done()
        
        self.processor_task = asyncio.create_task(process_jobs())
    
    async def send_webhook(self, webhook_url: str, job: Job):
        """Send webhook notification to the provided URL."""
        import aiohttp
        
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "job_id": job.id,
                    "status": job.status,
                    "query": job.query,
                    "result": job.result.dict() if job.result else None,
                    "error": job.error,
                    "completed_at": job.completed_at
                }
                
                async with session.post(webhook_url, json=payload) as response:
                    if response.status == 200:
                        print(f"📡 Webhook sent successfully to {webhook_url}")
                    else:
                        print(f"⚠️ Webhook failed with status {response.status}")
        except Exception as e:
            print(f"❌ Webhook error: {e}")


# ============== FastAPI App ==============

app = FastAPI(title="ChatGPT Scraper API", version="2.0.0")

# Global instances
browser_manager: Optional[BrowserManager] = None
scraper: Optional[ChatGPTScraper] = None
job_queue: JobQueue = JobQueue()
ws_manager: WebSocketManager = WebSocketManager()


@app.on_event("startup")
async def startup_event():
    """Initialize browser and scraper on startup."""
    global browser_manager, scraper
    
    print("🚀 Starting ChatGPT Scraper API Server...")
    print("🌐 API will be available at: http://localhost:3000")
    print("📡 WebSocket endpoint: ws://localhost:3000/ws/jobs/{job_id}")
    
    # Initialize browser and scraper
    browser_manager = BrowserManager(user_data_dir="production_api_profile")
    scraper = ChatGPTScraper()
    
    # Start background job processor
    await job_queue.start_processor(browser_manager, scraper, ws_manager)
    
    print("✅ Server ready!")


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up on shutdown."""
    print("🛑 Shutting down server...")
    if browser_manager:
        try:
            await browser_manager.stop()
        except:
            pass


# ============== API Endpoints ==============

@app.post("/api/scrape", response_model=JobSubmissionResponse)
async def create_scrape_job(request: ScrapeRequest):
    """Submit a new scraping job. Returns job_id immediately."""
    job_id = await job_queue.add_job(
        query=request.query,
        webhook_url=str(request.webhook_url) if request.webhook_url else None
    )
    
    return JobSubmissionResponse(
        job_id=job_id,
        status=JobStatus.PENDING,
        message="Job submitted successfully. Use /api/jobs/{job_id} to check status."
    )


@app.get("/api/jobs/{job_id}", response_model=Job)
async def get_job(job_id: str):
    """Get job status and result."""
    job = job_queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/jobs")
async def list_jobs():
    """List all jobs."""
    return {"jobs": job_queue.list_jobs()}


@app.websocket("/ws/jobs/{job_id}")
async def websocket_job_updates(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for real-time job updates."""
    await ws_manager.connect(websocket, job_id)
    
    try:
        # Send current job status immediately
        job = job_queue.get_job(job_id)
        if job:
            await websocket.send_json({
                "type": "job_update",
                "job": job.dict()
            })
        
        # Keep connection alive and listen for disconnect
        while True:
            await websocket.receive_text()
            
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, job_id)


# ============== Main ==============

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000, log_level="info")
