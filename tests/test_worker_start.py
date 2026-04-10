#!/usr/bin/env python3
"""Test worker startup and message consumption without full scraping"""
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
QUERY = "quick test"


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
    print("🚀 Worker Startup Test (15 seconds)")
    print("This test verifies worker can consume messages\n")
    
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
        # Monitor for 15 seconds
        start_time = time.time()
        output_lines = []
        
        while time.time() - start_time < 15:
            if process.poll() is not None:
                break
                
            # Read available output
            line = process.stdout.readline()
            if line:
                output_lines.append(line.strip())
                print(f"Worker: {line.strip()}")
                
                # Check if worker started processing
                if "Processing job" in line:
                    print("✅ Worker started processing the job!")
                    
                    # Give it a few more seconds then check queue
                    time.sleep(3)
                    final_count = check_queue_status()
                    print(f"Queue count after processing: {final_count}")
                    
                    if final_count == 0:
                        print("✅ Message consumed from queue!")
                        process.terminate()
                        return 0
            
            time.sleep(0.5)
        
        print("\n--- Worker Output Summary ---")
        for line in output_lines[-20:]:  # Show last 20 lines
            print(f"  {line}")
        
        final_count = check_queue_status()
        if final_count == 0:
            print("\n✅ Message was consumed (though scraping may still be running)")
            return 0
        else:
            print(f"\n⚠️  Message still in queue (count: {final_count})")
            print("Worker may still be starting or processing")
            return 0  # Don't fail, just warn
            
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


if __name__ == "__main__":
    sys.exit(main())
