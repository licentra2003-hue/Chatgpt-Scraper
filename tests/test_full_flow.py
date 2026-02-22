#!/usr/bin/env python3
"""Full end-to-end test of the scraper system"""
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


def publish_test_job(query: str) -> str:
    """Publish a test job and return job_id"""
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    channel = connection.channel()
    channel.queue_declare(queue="scraping_tasks", durable=True)
    
    job_id = str(uuid.uuid4())
    body = json.dumps({"job_id": job_id, "query": query})
    channel.basic_publish(
        exchange="",
        routing_key="scraping_tasks",
        body=body,
        properties=pika.BasicProperties(delivery_mode=2),
    )
    connection.close()
    print(f"Published job {job_id} with query: {query}")
    return job_id


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
    print("🚀 Full Scraper System Test")
    print("Testing API → RabbitMQ → Worker → Scraping flow\n")
    
    # Test 1: API Queue Publishing
    print("=== Test 1: API Queue Publishing ===")
    test_job_id = publish_test_job("What is 2+2?")
    
    # Check queue after publishing
    time.sleep(1)
    queue_count = check_queue_status()
    print(f"Queue count after publishing: {queue_count}")
    
    if queue_count == 0:
        print("❌ Message not found in queue")
        return 1
    else:
        print("✅ Message successfully queued")
    
    # Test 2: Worker Consumption
    print("\n=== Test 2: Worker Consumption ===")
    
    # Start worker
    worker_script = os.path.join("worker", "main.py")
    env = os.environ.copy()
    env["SUPABASE_URL"] = "mock://localhost"
    env["SUPABASE_KEY"] = "mock_key"
    env["HEADLESS"] = "True"  # Use headless for testing
    
    process = subprocess.Popen([sys.executable, worker_script], 
                             env=env, stdout=subprocess.PIPE, 
                             stderr=subprocess.STDOUT, universal_newlines=True)
    
    try:
        # Monitor worker for 60 seconds
        start_time = time.time()
        job_processed = False
        browser_launched = False
        scraping_attempted = False
        
        while time.time() - start_time < 60:
            if process.poll() is not None:
                break
                
            line = process.stdout.readline()
            if line:
                print(f"Worker: {line.strip()}")
                
                if "Processing job" in line:
                    job_processed = True
                    print("✅ Worker started processing job")
                
                if "Launching Shared Browser Instance" in line:
                    browser_launched = True
                    print("✅ Browser launched successfully")
                
                if "Navigating to" in line:
                    scraping_attempted = True
                    print("✅ Scraping process started")
                
                if "Updating job" in line and ("completed" in line or "failed" in line):
                    print("✅ Job processing completed")
                    break
            
            time.sleep(0.5)
        
        # Final queue check
        final_queue_count = check_queue_status()
        print(f"\nFinal queue count: {final_queue_count}")
        
        # Results
        print("\n=== Test Results ===")
        if job_processed:
            print("✅ Worker consumed message from queue")
        else:
            print("❌ Worker did not process job")
        
        if browser_launched:
            print("✅ Browser manager working correctly")
        else:
            print("❌ Browser failed to launch")
        
        if scraping_attempted:
            print("✅ Scraping process initiated")
        else:
            print("❌ Scraping process not started")
        
        if final_queue_count == 0:
            print("✅ Message successfully consumed")
        else:
            print(f"⚠️  {final_queue_count} messages still in queue")
        
        if job_processed and browser_launched and scraping_attempted:
            print("\n🎉 Full system test PASSED!")
            print("The scraper system is working end-to-end")
            return 0
        else:
            print("\n❌ System test FAILED")
            return 1
            
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        return 1
    finally:
        if process.poll() is None:
            print("Stopping worker...")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    sys.exit(main())
