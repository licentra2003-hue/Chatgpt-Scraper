"""
Test script for the production async API server.
Demonstrates:
1. Submitting a job and getting job_id immediately
2. Polling for job status
3. Getting final results
"""

import asyncio
import time
import httpx
import json

BASE_URL = "http://localhost:3000"


async def test_async_scrape():
    """Test the async scraping API."""
    print("🧪 Testing Production Async API Server")
    print("=" * 60)
    
    async with httpx.AsyncClient() as client:
        # 1. Submit a job
        print("\n1️⃣ Submitting scraping job...")
        query = "What is the best MMP platform for mobile apps?"
        
        response = await client.post(
            f"{BASE_URL}/api/scrape",
            json={"query": query}
        )
        
        if response.status_code != 200:
            print(f"❌ Failed to submit job: {response.text}")
            return
        
        job_data = response.json()
        job_id = job_data["job_id"]
        print(f"✅ Job submitted successfully!")
        print(f"   Job ID: {job_id}")
        print(f"   Status: {job_data['status']}")
        print(f"   Message: {job_data['message']}")
        
        # 2. Poll for job status
        print("\n2️⃣ Polling for job status...")
        start_time = time.time()
        timeout = 300  # 5 minutes
        poll_interval = 2  # 2 seconds
        
        while True:
            if time.time() - start_time > timeout:
                print(f"❌ Timeout waiting for job completion")
                break
            
            response = await client.get(f"{BASE_URL}/api/jobs/{job_id}")
            job = response.json()
            
            status = job["status"]
            elapsed = time.time() - start_time
            
            print(f"   [{elapsed:.1f}s] Status: {status}")
            
            if status in ["completed", "failed"]:
                print(f"\n3️⃣ Job finished in {elapsed:.1f} seconds!")
                break
            
            await asyncio.sleep(poll_interval)
        
        # 3. Get final result
        print("\n3️⃣ Getting final result...")
        response = await client.get(f"{BASE_URL}/api/jobs/{job_id}")
        job = response.json()
        
        print(f"   Final Status: {job['status']}")
        
        if job["status"] == "completed":
            print(f"   ✅ Success!")
            print(f"\n   Query: {job['result']['query']}")
            print(f"   Response Length: {len(job['result']['response_text'])} chars")
            print(f"   Sources Found: {job['result']['total_sources']}")
            
            # Show first 200 chars of response
            print(f"\n   Response Preview:")
            print(f"   {job['result']['response_text'][:200]}...")
            
            # Show first few sources
            if job['result']['source_links']:
                print(f"\n   Sample Sources:")
                for i, source in enumerate(job['result']['source_links'][:3], 1):
                    print(f"   {i}. {source['text']}")
                    print(f"      URL: {source['url']}")
        else:
            print(f"   ❌ Failed!")
            print(f"   Error: {job.get('error', 'Unknown error')}")
        
        # 4. List all jobs
        print("\n4️⃣ Listing all jobs...")
        response = await client.get(f"{BASE_URL}/api/jobs")
        jobs_data = response.json()
        
        print(f"   Total Jobs: {len(jobs_data['jobs'])}")
        for job in jobs_data['jobs'][:5]:  # Show first 5
            print(f"   - {job['id'][:8]}... | {job['status']} | {job['query'][:40]}...")


async def test_concurrent_jobs():
    """Test submitting multiple jobs concurrently."""
    print("\n\n🧪 Testing Concurrent Job Submission")
    print("=" * 60)
    
    queries = [
        "What is the best MMP platform?",
        "How does mobile attribution work?",
        "What are Appsflyer features?",
        "Branch vs Appsflyer comparison",
        "MMP pricing models"
    ]
    
    async with httpx.AsyncClient() as client:
        # Submit all jobs
        print("\n1️⃣ Submitting 5 jobs concurrently...")
        job_ids = []
        
        for i, query in enumerate(queries, 1):
            response = await client.post(
                f"{BASE_URL}/api/scrape",
                json={"query": query}
            )
            job_id = response.json()["job_id"]
            job_ids.append(job_id)
            print(f"   Job {i} submitted: {job_id[:8]}...")
        
        print(f"\n✅ All {len(job_ids)} jobs submitted!")
        
        # Wait for all to complete
        print("\n2️⃣ Waiting for all jobs to complete...")
        start_time = time.time()
        
        while True:
            completed = 0
            failed = 0
            
            for job_id in job_ids:
                response = await client.get(f"{BASE_URL}/api/jobs/{job_id}")
                job = response.json()
                
                if job["status"] == "completed":
                    completed += 1
                elif job["status"] == "failed":
                    failed += 1
            
            elapsed = time.time() - start_time
            total_finished = completed + failed
            print(f"   [{elapsed:.1f}s] Progress: {total_finished}/{len(job_ids)} "
                  f"(✅ {completed} completed, ❌ {failed} failed)")
            
            if total_finished == len(job_ids):
                break
            
            await asyncio.sleep(2)
        
        print(f"\n✅ All jobs finished in {elapsed:.1f} seconds!")
        
        # Show results
        print("\n3️⃣ Results Summary:")
        for i, job_id in enumerate(job_ids, 1):
            response = await client.get(f"{BASE_URL}/api/jobs/{job_id}")
            job = response.json()
            
            status_icon = "✅" if job["status"] == "completed" else "❌"
            sources = job["result"]["total_sources"] if job["result"] else 0
            
            print(f"   {status_icon} Job {i}: {job['status']}")
            print(f"      Query: {job['query'][:40]}...")
            print(f"      Sources: {sources}")


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("🚀 PRODUCTION API SERVER TEST SUITE")
    print("=" * 60)
    
    # Test 1: Single async job
    await test_async_scrape()
    
    # Test 2: Concurrent jobs
    await test_concurrent_jobs()
    
    print("\n" + "=" * 60)
    print("✅ All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
