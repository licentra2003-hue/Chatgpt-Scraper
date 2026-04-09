import asyncio
import json
import os
import shutil
import uuid
import pika
import requests
from dataclasses import asdict
from datetime import datetime, timedelta
from supabase import create_client, Client
from dotenv import load_dotenv
from scraper import BrowserManager, ChatGPTScraper, ProfilePool

load_dotenv()

# Setup
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RABBITMQ_URL = os.getenv("RABBITMQ_URL")
API_URL = os.getenv("API_URL", "http://api:3000")

# Mock database fallback - if URL is mock or invalid, set supabase to None
if SUPABASE_URL in ["mock://localhost", "your_supabase_url_here", "", None]:
    print("⚠️  Warning: Using mock database - worker will not persist results")
    supabase: Client = None
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Generate a unique identity for this worker container
WORKER_ID = f"worker_{str(uuid.uuid4())[:8]}"

# Initialize global profile pool
profile_pool = ProfilePool(pool_size=3)

async def process_job(ch, method, properties, body):
    profile_path = None
    browser_manager = None
    slot_index = None
    try:
        data = json.loads(body)
        job_id = data.get("job_id")
        query = data.get("query")

        # Checkout from pool or fallback
        try:
            slot_index, profile_path = await profile_pool.get_profile()
            print(f"[{WORKER_ID}] Checked out pooled profile slot {slot_index}")
        except Exception:
            profile_path = os.path.join(os.getcwd(), "profiles", str(job_id))
            print(f"[{WORKER_ID}] Falling back to per-job profile {job_id}")
            
        browser_manager = BrowserManager(user_data_dir=profile_path)

        print(f"[{WORKER_ID}] Processing Job: {job_id}")

        if supabase is None:
            raise Exception("Supabase client not initialized")

        scraper = ChatGPTScraper()

        try:
            page = await browser_manager.get_page()
            result = await scraper.scrape(page, query)

            # Save Result
            if result.success:
                # Send result back to API for streaming
                posted = False
                last_err = None
                safe_result = json.loads(json.dumps(asdict(result), default=str))
                for attempt in range(1, 4):
                    try:
                        resp = requests.post(
                            f"{API_URL}/api/result/{str(job_id)}",
                            json={"result": safe_result},
                            timeout=20,
                        )
                        print(
                            f"[{WORKER_ID}] Result POST to API job={job_id} attempt={attempt} status={resp.status_code}"
                        )
                        if 200 <= resp.status_code < 300:
                            posted = True
                            break
                        last_err = Exception(f"non-2xx status={resp.status_code} body={resp.text}")
                    except Exception as e:
                        last_err = e
                    await asyncio.sleep(2 * attempt)

                if not posted:
                    raise Exception(f"Failed to POST result to API: {last_err}")

                # Mark job as processed in processed_jobs table
                supabase.table("processed_jobs").update({
                    "processed_at": datetime.now().isoformat(),
                    "expires_at": (datetime.now() + timedelta(hours=24)).isoformat(),
                    "engine": "Chatgpt",
                }).eq("job_id", str(job_id)).execute()
                print(f"[{WORKER_ID}] Job {job_id} Completed.")
            else:
                raise Exception(result.error_message)

        except Exception as e:
            error_msg = str(e).lower()
            print(f"[{WORKER_ID}] Job {job_id} Failed: {e}")

            # === SMART CONTEXT ROTATION ===
            if "soft block" in error_msg or "cloudflare" in error_msg or "sign up" in error_msg or "shadow block" in error_msg:
                print(f"[{WORKER_ID}] 🚨 BLOCK DETECTED! Rotating Identity...")

                # 1. Close Browser
                if browser_manager is not None:
                    await browser_manager.close()

                # 2. Nuke Profile Folder (Reset Trust)
                if slot_index is not None:
                    profile_pool.mark_poisoned(slot_index)
                elif profile_path and os.path.exists(profile_path):
                    shutil.rmtree(profile_path)
                    print(f"[{WORKER_ID}] 🗑️ Profile deleted.")

                # 3. Restart (BrowserManager will auto-create fresh folder on next get_page)
                # We do NOT retry the job here to avoid infinite loops, we mark as failed.
                # The User can retry.

            # No failure persistence in processed_jobs schema

    except Exception as e:
        print(f"CRITICAL WORKER ERROR: {e}")
    finally:
        # Always close the browser
        try:
            if browser_manager is not None:
                await browser_manager.close()
        except Exception as e:
            print(f"[{WORKER_ID}] Warning: failed to close browser for job {locals().get('job_id')}: {e}")

        # Checkin pooled profile or delete fallback profile
        try:
            if slot_index is not None:
                profile_pool.return_profile(slot_index)
                print(f"[{WORKER_ID}] Returned pooled profile slot {slot_index}")
            elif profile_path and os.path.exists(profile_path):
                shutil.rmtree(profile_path)
        except Exception as e:
            print(f"[{WORKER_ID}] Warning: failed to manage profile dir {profile_path}: {e}")

        ch.basic_ack(delivery_tag=method.delivery_tag)

def run_worker():
    # Ensure profile dir exists
    if not os.path.exists("profiles"):
        os.makedirs("profiles")

    params = pika.URLParameters(RABBITMQ_URL)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    
    channel.queue_declare(queue='scraping_tasks', durable=True)
    channel.basic_qos(prefetch_count=1)
    
    # We need an async wrapper for the blocking Pika consumer
    print(f"[{WORKER_ID}] Waiting for tasks...")
    
    # Simple Asyncio Loop integration for Pika
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Use basic_consume with a callback that schedules the async task
    def on_message(ch, method, properties, body):
        loop.run_until_complete(process_job(ch, method, properties, body))

    channel.basic_consume(queue='scraping_tasks', on_message_callback=on_message)
    channel.start_consuming()

if __name__ == "__main__":
    run_worker()