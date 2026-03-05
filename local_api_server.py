#!/usr/bin/env python3

import asyncio
import json
import os
from dotenv import load_dotenv
load_dotenv()
import uuid
from datetime import datetime
from typing import Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

from worker.scraper import BrowserManager, ChatGPTScraper

# Models
class ScrapeRequest(BaseModel):
    query: str

class ScrapeResult(BaseModel):
    id: str
    query: str
    status: str
    result: Dict[str, Any] = None
    created_at: str
    completed_at: str = None
    error: str = None

# In-memory storage for testing
jobs: Dict[str, ScrapeResult] = {}

# FastAPI app
app = FastAPI(title="Scraper API Local", version="1.0.0")

# Global scraper instance
browser_manager = None
scraper = None

@app.on_event("startup")
async def startup_event():
    global browser_manager, scraper
    print("🚀 Starting Local Scraper API...")
    
    # Initialize browser and scraper
    browser_manager = BrowserManager("local_api_profile")
    scraper = ChatGPTScraper()
    
    print("✅ Local Scraper API ready!")

@app.on_event("shutdown")
async def shutdown_event():
    global browser_manager
    if browser_manager:
        await browser_manager.close()
        print("✅ Browser closed")

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "scraper-api-local"}

@app.post("/api/scrape", response_model=ScrapeResult)
async def create_scrape_job(request: ScrapeRequest):
    """Create a new scraping job and execute it immediately"""
    job_id = str(uuid.uuid4())
    created_at = datetime.now().isoformat()
    
    # Create job record
    job = ScrapeResult(
        id=job_id,
        query=request.query,
        status="processing",
        created_at=created_at
    )
    jobs[job_id] = job
    
    try:
        # Execute scraping immediately
        print(f"🔍 Processing job {job_id}: {request.query}")
        
        page = await browser_manager.get_page()
        result = await scraper.scrape(page, request.query)
        
        # Update job with results
        job.status = "completed" if result.success else "failed"
        job.completed_at = datetime.now().isoformat()
        job.result = {
            "query": result.query,
            "response_text": result.response_text,
            "source_links": [
                {
                    "text": link.text,
                    "url": link.url,
                    "title": link.title,
                    "description": link.description
                } for link in result.source_links
            ],
            "total_sources": result.total_sources,
            "success": result.success,
            "timestamp": result.timestamp
        }
        
        if not result.success:
            job.error = result.error_message
            
        print(f"✅ Job {job_id} completed successfully")
        
    except Exception as e:
        # Update job with error
        job.status = "failed"
        job.completed_at = datetime.now().isoformat()
        job.error = str(e)
        print(f"❌ Job {job_id} failed: {e}")
    
    return job

@app.get("/api/result/{job_id}", response_model=ScrapeResult)
async def get_job_result(job_id: str):
    """Get the result of a scraping job"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return jobs[job_id]

@app.get("/api/jobs")
async def list_jobs():
    """List all jobs"""
    return {"jobs": list(jobs.values())}

if __name__ == "__main__":
    print("🌐 Starting Local Scraper API Server...")
    print("📝 API will be available at: http://localhost:3005")
    print("🔗 Try: curl -X POST http://localhost:3005/api/scrape -H 'Content-Type: application/json' -d '{\"query\":\"What is the best MMP platform?\"}'")
    
    uvicorn.run(app, host="0.0.0.0", port=3005)
