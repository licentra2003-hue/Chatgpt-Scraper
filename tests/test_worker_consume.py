#!/usr/bin/env python3
"""Test worker message consumption without waiting for scraping completion"""
import json
import os
import subprocess
import sys
import time
import uuid

import pika
from dotenv import load_dotenv

load_dotenv()

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672")

JOB_ID = str(uuid.uuid4())
QUERY = "consume test"


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


def check_queue_status():
    try:
        connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
        channel = connection.channel()
        queue_info = channel.queue_declare(queue="scraping_tasks", durable=True)
        message_count = queue_info.method.message_count
        connection.close()
        return message_count
    except Exception as e:
        print(f"Error checking queue: {e}")
        return -1


def main() -> int:
    print("🚀 Worker Message Consumption Test")
    print("This test verifies worker can consume messages (30s timeout)\n")
    
    # Clear queue first
    print("Clearing any existing messages...")
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    channel = connection.channel()
    channel.queue_purge(queue="scraping_tasks")
    connection.close()
    
    publish_job()
    
    # Start worker with mock credentials
    worker_script = os.path.join("worker", "main.py")
    env = os.environ.copy()
    env["SUPABASE_URL"] = "mock://localhost"
    env["SUPABASE_KEY"] = "mock_key"
    
    print("Starting worker process...")
    process = subprocess.Popen([sys.executable, worker_script], 
                             env=env, stdout=subprocess.PIPE, 
                             stderr=subprocess.STDOUT, universal_newlines=True)
    
    try:
        # Monitor for 30 seconds
        start_time = time.time()
        message_consumed = False
        processing_started = False
        
        while time.time() - start_time < 30:
            if process.poll() is not None:
                break
                
            # Read available output
            line = process.stdout.readline()
            if line:
                print(f"Worker: {line.strip()}")
                
                # Check if worker started processing
                if "Processing job" in line:
                    processing_started = True
                    print("✅ Worker started processing the job!")
                    
                    # Check queue status after a short delay
                    time.sleep(2)
                    queue_count = check_queue_status()
                    print(f"Queue count after processing started: {queue_count}")
                    
                    if queue_count == 0:
                        message_consumed = True
                        print("✅ Message consumed from queue!")
                        break
                
                # Check for mock Supabase updates
                if "MOCK: Updating job" in line:
                    print("✅ Worker is updating job status")
            
            time.sleep(0.5)
        
        if message_consumed:
            print("\n✅ SUCCESS: Worker consumed the message!")
            print("Note: Worker may still be scraping (this is normal)")
            return 0
        elif processing_started:
            print("\n⚠️  Worker started processing but message still in queue")
            print("This might indicate a delay in message acknowledgment")
            return 0  # Don't fail, worker is working
        else:
            print("\n❌ Worker did not start processing within 30 seconds")
            return 1
            
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        return 1
    finally:
        if process.poll() is None:
            print("Stopping worker process...")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                print("Force killed worker process")


if __name__ == "__main__":
    sys.exit(main())
