#!/usr/bin/env python3
"""
API Flow Testing Script
Tests the complete API flow: POST -> Supabase -> RabbitMQ -> GET
"""

import os
import sys
import json
import time
import requests
import pika
from supabase import create_client
from dotenv import load_dotenv

def test_api_flow():
    """Test complete API flow"""
    print("🚀 Starting API Flow Test\n")
    
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
        
        # Step 2: Check Supabase for the job
        print("\n🔍 Step 2: Checking Supabase for job record...")
        
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_KEY')
        
        if not supabase_url or not supabase_key:
            print("❌ Supabase credentials not found")
            return False
        
        supabase = create_client(supabase_url, supabase_key)
        
        # Wait a moment for database write
        time.sleep(1)
        
        result = supabase.table('scraping_jobs').select('*').eq('id', job_id).execute()
        
        if len(result.data) == 0:
            print("❌ Job not found in Supabase")
            return False
        
        job_record = result.data[0]
        print(f"✅ Job found in Supabase with status: {job_record['status']}")
        
        # Step 3: Check RabbitMQ for the message
        print("\n🔍 Step 3: Checking RabbitMQ for queued message...")
        
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
        
        # Optional: Try to consume one message to verify format
        method_frame, header_frame, body = channel.basic_get(queue='scraping_tasks', auto_ack=True)
        
        if method_frame:
            message_data = json.loads(body.decode('utf-8'))
            if message_data.get('job_id') == job_id:
                print(f"✅ Correct message found for job {job_id}")
            else:
                print(f"⚠️  Found message but for different job: {message_data.get('job_id')}")
        else:
            print("⚠️  Could not retrieve message from queue")
        
        connection.close()
        
        # Step 4: Test GET endpoint
        print("\n🔍 Step 4: Testing GET /api/result/:id...")
        
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
        
        print("\n" + "="*50)
        print("✅ API & Queue Flow Working")
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
    print("   3. Supabase credentials are configured in .env")
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
