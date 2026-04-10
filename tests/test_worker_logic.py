#!/usr/bin/env python3
"""End-to-end worker verification"""
import json
import os
import subprocess
import sys
import time
import uuid

import pika
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Supabase credentials not configured. Populate SUPABASE_URL and SUPABASE_KEY in .env")
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

JOB_ID = str(uuid.uuid4())
QUERY = "worker test query"


def publish_job():
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    channel = connection.channel()
    channel.queue_declare(queue="scraping_tasks", durable=True)
    body = json.dumps({"job_id": JOB_ID, "query": QUERY})
    channel.basic_publish(
        exchange="",
        routing_key="scraping_tasks",
        body=body,
        properties=pika.BasicProperties(delivery_mode=2),
    )
    connection.close()
    print(f"Published job {JOB_ID} to RabbitMQ")


def seed_job_record():
    supabase.table("scraping_jobs").insert(
        {
            "id": JOB_ID,
            "query": QUERY,
            "status": "pending",
        }
    ).execute()
    print("Supabase job record inserted")


def monitor_job(timeout_seconds: int = 30) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = (
            supabase.table("scraping_jobs")
            .select("status")
            .eq("id", JOB_ID)
            .limit(1)
            .execute()
        )
        data = response.data
        if data and data[0].get("status") == "completed":
            return True
        time.sleep(2)
    return False


def main() -> int:
    seed_job_record()
    publish_job()

    worker_script = os.path.join("worker", "main.py")
    env = os.environ.copy()

    process = subprocess.Popen([sys.executable, worker_script], env=env)
    try:
        print("Worker started (30s window)")
        if monitor_job(timeout_seconds=30):
            print("\n✅ Worker Consumed & Scraped Successfully")
            return 0
        print("\n❌ Worker failed to mark job completed within timeout")
        return 1
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    sys.exit(main())
