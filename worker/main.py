import asyncio
import json
import os
import uuid
import pika
import requests
from dataclasses import asdict
from datetime import datetime, timedelta
from supabase import create_client, Client
from dotenv import load_dotenv
from scraper import ProfileManager, ManagedChatGPTScraper

load_dotenv()

# Setup
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RABBITMQ_URL = os.getenv("RABBITMQ_URL")
API_URL = os.getenv("API_URL", "http://api:3000")

# Mock database fallback
if SUPABASE_URL in ["mock://localhost", "your_supabase_url_here", "", None]:
    print("⚠️  Warning: Using mock database - worker will not persist results")
    supabase: Client = None
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Generate a unique identity for this worker container
WORKER_ID = f"worker_{str(uuid.uuid4())[:8]}"

# Single, shared ProfileManager — hands out the persistent profile directory
# to every job so cookies accumulate across runs.
profile_manager = ProfileManager(base_profiles_dir=os.path.join(os.getcwd(), "profiles"))


async def process_job(ch, method, properties, body):
    try:
        data = json.loads(body)
        job_id = data.get("job_id")
        query = data.get("query")

        print(f"[{WORKER_ID}] Processing Job: {job_id}")

        if supabase is None:
            raise Exception("Supabase client not initialized")

        # ManagedChatGPTScraper uses the persistent profile; it will NOT delete it
        # on exit — only close the browser.
        async with ManagedChatGPTScraper(profile_manager, job_id) as managed:
            try:
                result = await managed.scrape(query)

                if result.success:
                    # Post result back to API
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
                                f"[{WORKER_ID}] Result POST to API job={job_id} "
                                f"attempt={attempt} status={resp.status_code}"
                            )
                            if 200 <= resp.status_code < 300:
                                posted = True
                                break
                            last_err = Exception(
                                f"non-2xx status={resp.status_code} body={resp.text}"
                            )
                        except Exception as e:
                            last_err = e
                        await asyncio.sleep(2 * attempt)

                    if not posted:
                        raise Exception(f"Failed to POST result to API: {last_err}")

                    # Mark job as processed
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

                if (
                    "soft block" in error_msg
                    or "cloudflare" in error_msg
                    or "sign up" in error_msg
                    or "shadow block" in error_msg
                ):
                    print(f"[{WORKER_ID}] 🚨 BLOCK DETECTED — browser will close, "
                          f"persistent profile preserved for next run.")
                    # The ManagedChatGPTScraper.__aexit__ will close the browser.
                    # The profile directory is intentionally kept so accumulated
                    # cookies and TLS tickets are not lost.

    except Exception as e:
        print(f"CRITICAL WORKER ERROR: {e}")
    finally:
        ch.basic_ack(delivery_tag=method.delivery_tag)


def run_worker():
    # Ensure the persistent profile parent dir exists
    os.makedirs("profiles", exist_ok=True)

    params = pika.URLParameters(RABBITMQ_URL)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()

    channel.queue_declare(queue='scraping_tasks', durable=True)
    channel.basic_qos(prefetch_count=1)

    print(f"[{WORKER_ID}] Waiting for tasks...")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def on_message(ch, method, properties, body):
        loop.run_until_complete(process_job(ch, method, properties, body))

    channel.basic_consume(queue='scraping_tasks', on_message_callback=on_message)
    channel.start_consuming()


if __name__ == "__main__":
    run_worker()