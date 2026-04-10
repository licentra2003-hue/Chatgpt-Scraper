#!/usr/bin/env python3

import requests
import json
import time

def test_local_api():
    """Test the local API server with multiple MMP queries"""
    
    base_url = "http://localhost:3000"
    
    print("🚀 Testing Local API Server")
    print("=" * 50)
    
    # Test health endpoint
    try:
        response = requests.get(f"{base_url}/health")
        if response.status_code == 200:
            print("✅ API Server is healthy")
            print(f"📊 Health: {response.json()}")
        else:
            print(f"❌ Health check failed: {response.status_code}")
            return
    except Exception as e:
        print(f"❌ Cannot connect to API server: {e}")
        print("💡 Make sure the local API server is running on http://localhost:3000")
        return
    
    # Test queries
    queries = [
        "What is a Mobile Measurement Platform?",
        "Which MMP platform is best for gaming apps?",
        "AppsFlyer vs Adjust comparison",
        "What are MMP pricing models?",
        "How to choose the right MMP for e-commerce?"
    ]
    
    job_ids = []
    
    print(f"\n📝 Submitting {len(queries)} scraping jobs...")
    
    # Submit all jobs
    for i, query in enumerate(queries, 1):
        try:
            print(f"🔍 Job {i}: {query}")
            response = requests.post(
                f"{base_url}/api/scrape",
                headers={"Content-Type": "application/json"},
                json={"query": query}
            )
            
            if response.status_code == 200:
                job = response.json()
                job_ids.append(job['id'])
                print(f"✅ Job submitted: {job['id']} (Status: {job['status']})")
            else:
                print(f"❌ Failed to submit job: {response.status_code} - {response.text}")
                
        except Exception as e:
            print(f"❌ Error submitting job: {e}")
    
    print(f"\n⏳ Checking job results...")
    
    # Check results
    for job_id in job_ids:
        max_attempts = 30  # Wait up to 30 seconds per job
        attempts = 0
        
        while attempts < max_attempts:
            try:
                response = requests.get(f"{base_url}/api/result/{job_id}")
                
                if response.status_code == 200:
                    job = response.json()
                    
                    if job['status'] in ['completed', 'failed']:
                        print(f"\n📋 Job {job_id[:8]}... - {job['status'].upper()}")
                        
                        if job['status'] == 'completed' and job['result']:
                            result = job['result']
                            print(f"✅ Query: {result['query']}")
                            print(f"📝 Response: {result['response_text'][:100]}...")
                            print(f"📚 Sources: {result['total_sources']}")
                            print(f"⏱️  Duration: {job['created_at']} → {job['completed_at']}")
                        else:
                            print(f"❌ Error: {job.get('error', 'Unknown error')}")
                        break
                    else:
                        print(f"⏳ Job {job_id[:8]}... still {job['status']}...")
                        time.sleep(1)
                        attempts += 1
                else:
                    print(f"❌ Failed to get job result: {response.status_code}")
                    break
                    
            except Exception as e:
                print(f"❌ Error checking job: {e}")
                break
        
        if attempts >= max_attempts:
            print(f"⏰ Job {job_id[:8]}... timed out")
    
    print(f"\n🎯 API Testing Complete!")

if __name__ == "__main__":
    test_local_api()
