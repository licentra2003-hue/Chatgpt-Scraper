"""
Test script for webhook functionality.
Demonstrates submitting jobs with webhook URLs for completion notifications.
"""

import asyncio
import httpx
from fastapi import FastAPI, Request
import uvicorn
import threading


# Simple webhook receiver server
webhook_app = FastAPI()
webhook_received = []
webhook_server_port = 8001


@webhook_app.post("/webhook")
async def receive_webhook(request: Request):
    """Receive webhook notifications."""
    data = await request.json()
    webhook_received.append(data)
    print(f"\n📡 Webhook Received!")
    print(f"   Job ID: {data.get('job_id')}")
    print(f"   Status: {data.get('status')}")
    print(f"   Query: {data.get('query')[:50]}...")
    
    if data.get('result'):
        result = data['result']
        print(f"   Response Length: {len(result.get('response_text', ''))} chars")
        print(f"   Sources: {result.get('total_sources', 0)}")
    
    if data.get('error'):
        print(f"   Error: {data['error']}")
    
    return {"status": "received"}


def run_webhook_server():
    """Run webhook server in background thread."""
    uvicorn.run(webhook_app, host="127.0.0.1", port=webhook_server_port, log_level="error")


async def test_webhook():
    """Test webhook functionality."""
    print("🧪 Testing Webhook Functionality")
    print("=" * 60)
    
    # Start webhook server in background
    print("\n1️⃣ Starting webhook receiver server...")
    webhook_thread = threading.Thread(target=run_webhook_server, daemon=True)
    webhook_thread.start()
    await asyncio.sleep(2)  # Give server time to start
    print(f"✅ Webhook server running on http://127.0.0.1:{webhook_server_port}/webhook")
    
    # Submit job with webhook URL
    print("\n2️⃣ Submitting job with webhook URL...")
    webhook_url = f"http://127.0.0.1:{webhook_server_port}/webhook"
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:3000/api/scrape",
            json={
                "query": "What is the best MMP platform for mobile apps?",
                "webhook_url": webhook_url
            }
        )
        
        if response.status_code != 200:
            print(f"❌ Failed to submit job: {response.text}")
            return
        
        job_id = response.json()["job_id"]
        print(f"✅ Job submitted: {job_id}")
        print(f"   Webhook URL: {webhook_url}")
        
        # Wait for webhook to be received
        print("\n3️⃣ Waiting for webhook notification...")
        start_time = asyncio.get_event_loop().time()
        
        while not webhook_received:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > 300:  # 5 minute timeout
                print(f"⏱️ Timeout waiting for webhook")
                break
            await asyncio.sleep(1)
            print(f"   [{elapsed:.1f}s] Waiting...", end="\r")
        
        if webhook_received:
            print(f"\n✅ Webhook received after {elapsed:.1f} seconds!")
            
            # Verify webhook data
            webhook_data = webhook_received[0]
            print("\n4️⃣ Webhook Data Verification:")
            print(f"   Job ID Match: {webhook_data['job_id'] == job_id}")
            print(f"   Status: {webhook_data['status']}")
            print(f"   Has Result: {'result' in webhook_data}")
            print(f"   Has Timestamp: {'completed_at' in webhook_data}")
            
            if webhook_data.get('status') == 'completed':
                print("\n5️⃣ Result Preview:")
                result = webhook_data['result']
                print(f"   Query: {result['query']}")
                print(f"   Response: {result['response_text'][:200]}...")
                print(f"   Sources: {result['total_sources']}")
        
        # Clean up
        print("\n6️⃣ Cleanup:")
        response = await client.get(f"http://localhost:3000/api/jobs/{job_id}")
        print(f"   Job Status: {response.json()['status']}")


async def test_multiple_webhooks():
    """Test multiple jobs with webhooks."""
    print("\n\n🧪 Testing Multiple Jobs with Webhooks")
    print("=" * 60)
    
    queries = [
        "What is the best MMP platform?",
        "How does mobile attribution work?",
        "Appsflyer vs Branch comparison"
    ]
    
    webhook_url = f"http://127.0.0.1:{webhook_server_port}/webhook"
    job_ids = []
    
    # Clear previous webhooks
    webhook_received.clear()
    
    # Submit all jobs
    print("\n1️⃣ Submitting 3 jobs with webhook URLs...")
    async with httpx.AsyncClient() as client:
        for i, query in enumerate(queries, 1):
            response = await client.post(
                "http://localhost:3000/api/scrape",
                json={
                    "query": query,
                    "webhook_url": webhook_url
                }
            )
            job_id = response.json()["job_id"]
            job_ids.append(job_id)
            print(f"   Job {i}: {job_id[:8]}... - {query[:30]}...")
    
    # Wait for all webhooks
    print("\n2️⃣ Waiting for all webhook notifications...")
    start_time = asyncio.get_event_loop().time()
    
    while len(webhook_received) < len(job_ids):
        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed > 300:
            print(f"⏱️ Timeout waiting for webhooks")
            break
        await asyncio.sleep(1)
        print(f"   [{elapsed:.1f}s] Webhooks: {len(webhook_received)}/{len(job_ids)}", end="\r")
    
    print(f"\n✅ All {len(webhook_received)} webhooks received!")
    
    # Show results
    print("\n3️⃣ Results Summary:")
    for i, webhook_data in enumerate(webhook_received, 1):
        status_icon = "✅" if webhook_data['status'] == "completed" else "❌"
        print(f"   {status_icon} Job {i}: {webhook_data['status']}")
        print(f"      Query: {webhook_data['query'][:40]}...")
        
        if webhook_data.get('result'):
            sources = webhook_data['result']['total_sources']
            print(f"      Sources: {sources}")


async def main():
    """Run all webhook tests."""
    await test_webhook()
    await test_multiple_webhooks()
    
    print("\n" + "=" * 60)
    print("✅ All webhook tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
