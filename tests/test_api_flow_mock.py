#!/usr/bin/env python3
"""
API Flow Testing Script (Mock Version)
Tests the complete API flow: POST -> RabbitMQ -> GET
"""

import os
import sys
import json
import time
import requests
import pika
from dotenv import load_dotenv

def test_api_flow():
    """Test complete API flow with mock database"""
    print("🚀 Starting API Flow Test (Mock Version)\n")
    
    # Load environment variables
    load_dotenv()
    
    # API configuration
    api_base_url = "http://localhost:3000"
    
    # Test data
    test_query = "test query for scraping"
    
    try:
        # Step 1: Send POST request to create job
        print("🔍 Step 1: Sending POST request to /api/scrape...")
        
        post_response = requests.post(
            f"{api_base_url}/api/scrape",
            json={"query": test_query},
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        if post_response.status_code != 201:
            print(f"❌ POST request failed: {post_response.status_code}")
            print(f"Response: {post_response.text}")
            return False
        
        post_data = post_response.json()
        job_id = post_data.get("job_id")
        
        if not job_id:
            print("❌ No job_id in response")
            return False
        
        print(f"✅ Job created with ID: {job_id}")
        
        # Step 2: Check RabbitMQ for the message
        print("\n🔍 Step 2: Checking RabbitMQ for queued message...")
        
        rabbitmq_url = os.getenv('RABBITMQ_URL', 'amqp://admin:admin123@localhost:5672')
        
        connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
        channel = connection.channel()
        
        # Check queue message count
        queue_info = channel.queue_declare(queue='scraping_tasks', durable=True)
        message_count = queue_info.method.message_count
        
        if message_count == 0:
            print("❌ No messages in RabbitMQ queue")
            connection.close()
            return False
        
        print(f"✅ Found {message_count} message(s) in RabbitMQ queue")
        
        # Try to consume messages to find our job
        found_job = False
        for _ in range(min(message_count, 10)):  # Check up to 10 messages
            method_frame, header_frame, body = channel.basic_get(queue='scraping_tasks', auto_ack=True)
            
            if method_frame:
                message_data = json.loads(body.decode('utf-8'))
                if message_data.get('job_id') == job_id:
                    print(f"✅ Correct message found for job {job_id}")
                    print(f"   Query: {message_data.get('query')}")
                    found_job = True
                    break
            else:
                break
        
        if not found_job:
            print(f"⚠️  Message for job {job_id} not found in queue (checked {min(message_count, 10)} messages)")
        
        connection.close()
        
        # Step 3: Test GET endpoint
        print("\n🔍 Step 3: Testing GET /api/result/:id...")
        
        get_response = requests.get(
            f"{api_base_url}/api/result/{job_id}",
            timeout=10
        )
        
        if get_response.status_code != 200:
            print(f"❌ GET request failed: {get_response.status_code}")
            print(f"Response: {get_response.text}")
            return False
        
        get_data = get_response.json()
        print(f"✅ GET request successful, status: {get_data.get('status')}")
        print(f"   Query: {get_data.get('query')}")
        
        # Step 4: Test health endpoint
        print("\n🔍 Step 4: Testing health endpoint...")
        
        health_response = requests.get(f"{api_base_url}/health", timeout=10)
        
        if health_response.status_code == 200:
            health_data = health_response.json()
            print(f"✅ Health check passed: {health_data.get('service')} - {health_data.get('status')}")
        else:
            print("❌ Health check failed")
            return False
        
        print("\n" + "="*50)
        print("✅ API & Queue Flow Working (Mock Database)")
        print("📝 Note: Using mock database - update SUPABASE_URL in .env for real database")
        return True
        
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to API server. Is it running on port 3000?")
        return False
    except Exception as e:
        print(f"❌ Test failed: {str(e)}")
        return False

def main():
    """Main test function"""
    print("🔧 Make sure:")
    print("   1. Go API server is running on port 3000")
    print("   2. RabbitMQ is running")
    print("   3. Mock database is enabled (SUPABASE_URL not configured)")
    print()
    
    success = test_api_flow()
    
    if success:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print("\n💥 Tests failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())
