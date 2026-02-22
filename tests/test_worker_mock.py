#!/usr/bin/env python3
"""Mock worker verification without Supabase"""
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


def check_queue_empty_once() -> bool:
    """Check queue status once"""
    try:
        connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
        channel = connection.channel()
        queue_info = channel.queue_declare(queue="scraping_tasks", durable=True)
        message_count = queue_info.method.message_count
        connection.close()
        
        print(f"Queue message count: {message_count}")
        return message_count == 0
    except Exception as e:
        print(f"Error checking queue: {e}")
        return False


def check_queue_empty(timeout_seconds: int = 30) -> bool:
    """Check if queue becomes empty (messages consumed)"""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
            channel = connection.channel()
            queue_info = channel.queue_declare(queue="scraping_tasks", durable=True)
            message_count = queue_info.method.message_count
            connection.close()
            
            if message_count == 0:
                return True
            print(f"Queue still has {message_count} messages...")
            time.sleep(3)
        except Exception as e:
            print(f"Error checking queue: {e}")
            time.sleep(3)
    return False


def main() -> int:
    timeout_seconds = 30
    print("🚀 Starting Worker Test (Mock Version)")
    print("Note: This test only verifies RabbitMQ consumption")
    print("Full end-to-end requires Supabase credentials\n")
    
    publish_job()
    
    # Start worker process
    worker_script = os.path.join("worker", "main.py")
    env = os.environ.copy()
    
    # Mock Supabase credentials to avoid errors
    env["SUPABASE_URL"] = "mock://localhost"
    env["SUPABASE_KEY"] = "mock_key"
    
    process = subprocess.Popen([sys.executable, worker_script], env=env, 
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                           universal_newlines=True)
    
    try:
        print("Worker started (30s window)")
        
        # Monitor worker output
        output_lines = []
        start_time = time.time()
        
        while time.time() - start_time < timeout_seconds:
            if process.poll() is not None:
                break
                
            # Read available output
            line = process.stdout.readline()
            if line:
                output_lines.append(line.strip())
                print(f"Worker: {line.strip()}")
            
            # Check queue every few seconds
            if time.time() - start_time > 5:  # Start checking after 5 seconds
                if check_queue_empty_once():
                    print("\n✅ Worker Consumed Message Successfully")
                    print("Worker output summary:")
                    for line in output_lines[-10:]:  # Show last 10 lines
                        print(f"  {line}")
                    process.terminate()
                    return 0
            
            time.sleep(1)
        
        # If we get here, timeout occurred
        print(f"\n❌ Worker failed to consume message within {timeout_seconds} seconds")
        print("Worker output summary:")
        for line in output_lines[-10:]:  # Show last 10 lines
            print(f"  {line}")
        return 1
            
    except subprocess.TimeoutExpired:
        print("\n❌ Worker process timeout")
        process.kill()
        return 1
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        process.terminate()
        return 1
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    sys.exit(main())
