#!/usr/bin/env python3
"""Simple RabbitMQ consumption test without scraping"""
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
QUERY = "simple test query"


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
    print("🚀 Simple Queue Consumption Test")
    print("This test only verifies RabbitMQ message consumption\n")
    
    # Check initial queue status
    initial_count = check_queue_status()
    print(f"Initial queue count: {initial_count}")
    
    publish_job()
    
    # Check queue after publishing
    after_publish_count = check_queue_status()
    print(f"After publishing count: {after_publish_count}")
    
    # Create a simple consumer script
    consumer_script = '''
import json
import pika
import os
from dotenv import load_dotenv

load_dotenv()
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672")

def handle_message(ch, method, properties, body):
    payload = json.loads(body)
    job_id = payload.get("job_id")
    query = payload.get("query")
    print(f"Received job: {job_id}, query: {query}")
    ch.basic_ack(delivery_tag=method.delivery_tag)
    print("Message acknowledged, stopping consumer")
    ch.stop_consuming()

try:
    connection = pika.BlockingConnection(pika.URLParameters(RABBITMQ_URL))
    channel = connection.channel()
    channel.queue_declare(queue="scraping_tasks", durable=True)
    channel.basic_consume(queue="scraping_tasks", on_message_callback=handle_message)
    print("Waiting for message...")
    channel.start_consuming()
except Exception as e:
    print(f"Consumer error: {e}")
finally:
    if 'connection' in locals():
        connection.close()
'''
    
    # Write consumer script to temp file
    with open('temp_consumer.py', 'w') as f:
        f.write(consumer_script)
    
    try:
        print("Starting simple consumer...")
        env = os.environ.copy()
        process = subprocess.Popen([sys.executable, 'temp_consumer.py'], 
                                 env=env, stdout=subprocess.PIPE, 
                                 stderr=subprocess.STDOUT, universal_newlines=True)
        
        # Wait for process with timeout
        try:
            stdout, stderr = process.communicate(timeout=10)
            print("Consumer output:")
            print(stdout)
            
            if process.returncode == 0:
                # Check final queue status
                final_count = check_queue_status()
                print(f"Final queue count: {final_count}")
                
                if final_count < after_publish_count:
                    print("\n✅ Message consumed successfully!")
                    return 0
                else:
                    print("\n❌ Message was not consumed")
                    return 1
            else:
                print(f"Consumer failed with return code: {process.returncode}")
                return 1
                
        except subprocess.TimeoutExpired:
            print("Consumer timed out, killing process...")
            process.kill()
            return 1
            
    finally:
        # Clean up temp file
        try:
            os.remove('temp_consumer.py')
        except:
            pass


if __name__ == "__main__":
    sys.exit(main())
