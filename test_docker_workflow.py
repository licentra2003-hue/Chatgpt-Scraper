#!/usr/bin/env python3
"""
Docker Deployment Test Script
Tests the complete Docker workflow: API → RabbitMQ → Worker → Result
"""

import os
import sys
import json
import time
import requests

def test_docker_workflow():
    """Test complete Docker deployed workflow"""
    print("🐳 Starting Docker Deployment Test\n")
    
    # Docker configuration
    api_base_url = "http://localhost:3001"  # Docker API port
    rabbitmq_url = "amqp://admin:admin123@localhost:5673"  # Docker RabbitMQ port
    
    # Test data
    test_query = "What is the best MMP platform for mobile apps?"
    
    try:
        # Step 1: Check API health
        print("🔍 Step 1: Checking API health...")
        health_response = requests.get(f"{api_base_url}/health", timeout=10)
        
        if health_response.status_code != 200:
            print(f"❌ Health check failed: {health_response.status_code}")
            return False
        
        health_data = health_response.json()
        print(f"✅ API Health: {health_data.get('service')} - {health_data.get('status')}")
        
        # Step 2: Send POST request to create job
        print("\n🔍 Step 2: Sending POST request to /api/scrape...")
        
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
        
        # Poll for job completion
        print("🔍 Polling for job completion...")
        start_time = time.time()
        timeout = 120  # 120 seconds timeout
        
        while time.time() - start_time < timeout:
            response = requests.get(f"{api_base_url}/api/result/{job_id}")
            if response.status_code == 200:
                result = response.json()
                status = result.get("status")
                print(f"📊 Job status: {status}")
                if status == "completed":
                    print("✅ Job completed successfully!")
                    print(f"📝 Result: {result.get('result', 'N/A')}")
                    return True
            time.sleep(2)
        
        print("❌ Job did not complete within timeout")
        return False
    
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to API server. Is Docker running?")
        print("   API should be on http://localhost:3001")
        return False
    except Exception as e:
        print(f"❌ Test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main test function"""
    print("🔧 Prerequisites:")
    print("   1. Docker Compose is running: docker-compose up -d")
    print("   2. API is accessible on http://localhost:3001")
    print("   3. RabbitMQ is accessible on localhost:5673")
    print()
    
    success = test_docker_workflow()
    
    if success:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print("\n💥 Tests failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())
