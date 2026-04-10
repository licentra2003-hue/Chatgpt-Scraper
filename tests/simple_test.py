#!/usr/bin/env python3

import json
import time
import requests
import uuid

def test_api():
    """Simple test for the API"""
    base_url = "http://localhost:3000"
    
    print("🚀 Testing Polyglot Scraper API")
    print(f"📍 API URL: {base_url}")
    
    # Test health endpoint
    try:
        response = requests.get(f"{base_url}/health")
        print(f"✅ Health check: {response.json()}")
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False
    
    # Test scrape endpoint
    job_ids = []
    for i in range(5):
        try:
            payload = {"query": f"Test query {i+1}: What is the meaning of life?"}
            response = requests.post(
                f"{base_url}/api/scrape",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code in [200, 201]:
                job_id = response.json().get("job_id")
                job_ids.append(job_id)
                print(f"📤 Request {i+1}: Job ID {job_id}")
            else:
                print(f"❌ Request {i+1} failed: {response.status_code} - {response.text}")
                
        except Exception as e:
            print(f"❌ Request {i+1} error: {e}")
    
    # Check job status
    print(f"\n⏳ Checking {len(job_ids)} job statuses...")
    for i, job_id in enumerate(job_ids):
        try:
            response = requests.get(f"{base_url}/api/result/{job_id}")
            if response.status_code == 200:
                result = response.json()
                status = result.get("status", "unknown")
                print(f"📊 Job {i+1} ({job_id[:8]}...): {status}")
            else:
                print(f"❌ Failed to get job {i+1} status: {response.status_code}")
        except Exception as e:
            print(f"❌ Error checking job {i+1}: {e}")
    
    print(f"\n🎯 Test completed! Sent {len(job_ids)} requests to the API.")
    return True

if __name__ == "__main__":
    test_api()
