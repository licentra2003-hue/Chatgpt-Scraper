"""
Concurrent ChatGPT Scraper Worker
==================================
Architecture:
  - 1 worker process  → 1 shared Chromium browser process
  - 1 browser process → up to JOBS_PER_WORKER isolated BrowserContexts
  - Each BrowserContext handles exactly 1 scraping job concurrently
  - Total capacity = NUM_WORKERS (docker replicas) × JOBS_PER_WORKER
                   = 5 × 4 = 20 simultaneous queries
"""

import asyncio
import json
import os
import uuid
import random
import requests
from dataclasses import asdict
from datetime import datetime, timedelta

import aio_pika
from supabase import create_client, Client
from dotenv import load_dotenv

from scraper import SharedBrowser, ChatGPTScraper

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────
SUPABASE_URL      = os.getenv("SUPABASE_URL")
SUPABASE_KEY      = os.getenv("SUPABASE_KEY")
RABBITMQ_URL      = os.getenv("RABBITMQ_URL")
API_URL           = os.getenv("API_URL", "http://api:3000")
SAVE_IN_SUPABASE  = os.getenv("SAVE_IN_SUPABASE", "false").lower() == "true"
CALLBACK_URL      = os.getenv("CALLBACK_URL")
JOBS_PER_WORKER   = int(os.getenv("JOBS_PER_WORKER", "4"))   # concurrent slots

# ── Supabase client ───────────────────────────────────────────────────────
if SUPABASE_URL in ["mock://localhost", "your_supabase_url_here", "", None]:
    print("Warning: Using mock database - worker will not persist results")
    supabase: Client = None
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Worker identity ───────────────────────────────────────────────────────
WORKER_ID = f"worker_{str(uuid.uuid4())[:8]}"


# ─────────────────────────────────────────────────────────────────────────
# Single-job processor
# ─────────────────────────────────────────────────────────────────────────
async def process_job(shared_browser: SharedBrowser, data: dict):
    """
    Process one scraping job inside an isolated BrowserContext drawn from
    the worker's shared browser process.
    """
    job_id      = data.get("job_id")
    query       = data.get("query")
    product_id  = data.get("product_id")
    snapshot_id = data.get("snapshot_id")
    callback_url = data.get("callback_url")

    print(f"[{WORKER_ID}] Starting job {job_id} | query: {query[:60]}...")

    # Add jitter to stagger workers so they don't all hit the login page simultaneously
    jitter = random.uniform(2, 5)
    print(f"[{WORKER_ID}] Applying jitter of {jitter:.1f}s...")
    await asyncio.sleep(jitter)

    if supabase is None:
        raise Exception("Supabase client not initialized")

    scraper = ChatGPTScraper()

    # Each job gets its own isolated browser context (cookies/storage isolated)
    async with shared_browser.new_context() as (ctx, bm):
        page = await ctx.new_page()
        await page.add_init_script(shared_browser.stealth_js)
        page.set_default_timeout(60000)

        result = await scraper.scrape(page, query, bm)

    if not result.success:
        raise Exception(result.error_message or "Scraper returned success=False")

    safe_result = json.loads(json.dumps(asdict(result), default=str))

    # ── Mark job as completed in processed_jobs ──────────────────────────
    try:
        supabase.table("processed_jobs").update({
            "processed_at": datetime.now().isoformat(),
            "expires_at":   (datetime.now() + timedelta(hours=24)).isoformat(),
            "engine":       "Chatgpt",
            "status":       "completed",
            "worker_id":    WORKER_ID,
        }).eq("job_id", str(job_id)).execute()
        print(f"[{WORKER_ID}] Job {job_id} status updated to completed.")
    except Exception as upd_err:
        print(f"[{WORKER_ID}] Failed to mark job {job_id} as completed: {upd_err}")

    # ── Persistence / Webhook ────────────────────────────────────────────
    if SAVE_IN_SUPABASE:
        if product_id is not None:
            try:
                record = {
                    "product_id":           product_id,
                    "optimization_prompt":  query,
                    "optimization_analysis": None,
                    "citations":            safe_result.get("source_links", []),
                    "raw_serp_results":     safe_result,
                    "snapshot_id":          snapshot_id,
                }
                supabase.table("product_analysis_chatgpt").insert(record).execute()
                print(f"[{WORKER_ID}] Job {job_id} saved to product_analysis_chatgpt.")
            except Exception as ins_e:
                print(f"[{WORKER_ID}] Error saving to Supabase: {ins_e}")
    else:
        # Use job-specific callback if provided, fallback to .env variable
        target_callback = callback_url or CALLBACK_URL
        if target_callback:
            try:
                wh = requests.post(
                    target_callback,
                    json={"job_id": job_id, "result": safe_result},
                    timeout=15,
                )
                print(f"[{WORKER_ID}] Webhook sent to {target_callback} (status {wh.status_code})")
            except Exception as cb_err:
                print(f"[{WORKER_ID}] Webhook failed for {target_callback}: {cb_err}")


# ─────────────────────────────────────────────────────────────────────────
# Message handler (called for every RabbitMQ delivery)
# ─────────────────────────────────────────────────────────────────────────
async def on_message(
    message: aio_pika.IncomingMessage,
    shared_browser: SharedBrowser,
    semaphore: asyncio.Semaphore,
):
    """
    Acquire a concurrency slot, process the job, then ack/nack the message.
    The semaphore ensures at most JOBS_PER_WORKER jobs run simultaneously.
    """
    async with semaphore:
        async with message.process(requeue=True):
            data = json.loads(message.body)
            job_id = data.get("job_id", "unknown")
            
            max_attempts = 3
            success = False
            
            for attempt in range(1, max_attempts + 1):
                try:
                    await process_job(shared_browser, data)
                    success = True
                    break # Exit loop on success
                except Exception as e:
                    error_msg = str(e).lower()
                    print(f"[{WORKER_ID}] Job {job_id} Attempt {attempt} FAILED: {e}")
                    
                    if attempt < max_attempts:
                        wait_time = random.uniform(5, 15)
                        print(f"[{WORKER_ID}] Retrying job {job_id} in {wait_time:.1f}s...")
                        await asyncio.sleep(wait_time)
                    else:
                        # Final failure after all retries
                        print(f"[{WORKER_ID}] Job {job_id} failed after {max_attempts} attempts.")
                        try:
                            supabase.table("processed_jobs").update({
                                "processed_at": datetime.now().isoformat(),
                                "status": "failed",
                                "worker_id": WORKER_ID,
                            }).eq("job_id", str(job_id)).execute()
                        except Exception as update_err:
                            print(f"[{WORKER_ID}] Failed to update failure status in DB: {update_err}")

                    # Smart block detection logic (remains active for each attempt)
                    if any(kw in error_msg for kw in ("soft block", "cloudflare", "sign up", "shadow block")):
                        print(f"[{WORKER_ID}] Block detected on job {job_id}. Attempt {attempt} used a fresh context.")


# ─────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────
async def main():
    os.makedirs("profiles", exist_ok=True)

    # One shared browser for this worker container
    shared_browser = SharedBrowser(worker_id=WORKER_ID)
    await shared_browser.start()

    # Semaphore caps concurrent jobs to JOBS_PER_WORKER (default 4)
    semaphore = asyncio.Semaphore(JOBS_PER_WORKER)

    print(f"[{WORKER_ID}] Connecting to RabbitMQ...")
    connection = await aio_pika.connect_robust(RABBITMQ_URL)

    async with connection:
        channel = await connection.channel()
        # prefetch = JOBS_PER_WORKER so RabbitMQ delivers exactly that many
        # unacked messages to this worker at a time
        await channel.set_qos(prefetch_count=JOBS_PER_WORKER)

        queue = await channel.declare_queue("scraping_tasks", durable=True)
        print(f"[{WORKER_ID}] Ready — consuming up to {JOBS_PER_WORKER} concurrent jobs.")

        # consume() returns an async iterator; we schedule each delivery as
        # an independent asyncio task so jobs truly run in parallel
        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                asyncio.create_task(
                    on_message(message, shared_browser, semaphore)
                )


if __name__ == "__main__":
    asyncio.run(main())