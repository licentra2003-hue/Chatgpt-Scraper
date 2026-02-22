"""
Test script for WebSocket real-time updates.
Demonstrates connecting to WebSocket and receiving live job updates.
"""

import asyncio
import websockets
import json


async def test_websocket_updates():
    """Test WebSocket connection for real-time job updates."""
    print("🧪 Testing WebSocket Real-time Updates")
    print("=" * 60)
    
    # First, submit a job
    print("\n1️⃣ Submitting a job...")
    import httpx
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:3000/api/scrape",
            json={"query": "What is the best MMP platform?"}
        )
        job_id = response.json()["job_id"]
        print(f"✅ Job submitted: {job_id}")
    
    # Connect to WebSocket
    print(f"\n2️⃣ Connecting to WebSocket...")
    ws_url = f"ws://localhost:3000/ws/jobs/{job_id}"
    
    try:
        async with websockets.connect(ws_url) as websocket:
            print(f"✅ Connected to WebSocket")
            
            # Listen for updates
            print(f"\n3️⃣ Listening for real-time updates...")
            print("-" * 60)
            
            while True:
                try:
                    message = await asyncio.wait_for(
                        websocket.recv(), 
                        timeout=300  # 5 minute timeout
                    )
                    
                    data = json.loads(message)
                    
                    if data["type"] == "job_update":
                        job = data["job"]
                        status = job["status"]
                        
                        timestamp = job.get("completed_at") or job.get("created_at")
                        print(f"\n📡 Update Received at {timestamp}")
                        print(f"   Status: {status}")
                        print(f"   Query: {job['query'][:50]}...")
                        
                        if status == "processing":
                            print(f"   🔄 Scraping in progress...")
                        elif status == "completed":
                            print(f"   ✅ Scraping completed!")
                            if job.get("result"):
                                result = job["result"]
                                print(f"   Response Length: {len(result['response_text'])} chars")
                                print(f"   Sources Found: {result['total_sources']}")
                                print(f"\n   Response Preview:")
                                print(f"   {result['response_text'][:200]}...")
                            break
                        elif status == "failed":
                            print(f"   ❌ Scraping failed!")
                            print(f"   Error: {job.get('error', 'Unknown error')}")
                            break
                        else:
                            print(f"   ⏳ Job is {status}...")
                
                except asyncio.TimeoutError:
                    print(f"\n⏱️ Timeout waiting for updates")
                    break
                except websockets.exceptions.ConnectionClosed:
                    print(f"\n🔌 WebSocket connection closed")
                    break
    
    except Exception as e:
        print(f"❌ WebSocket error: {e}")
    
    print("\n" + "=" * 60)
    print("✅ WebSocket test completed!")


async def test_websocket_multiple_jobs():
    """Test WebSocket with multiple concurrent jobs."""
    print("\n\n🧪 Testing WebSocket with Multiple Jobs")
    print("=" * 60)
    
    import httpx
    
    queries = [
        "What is the best MMP platform?",
        "How does mobile attribution work?",
        "Appsflyer vs Branch comparison"
    ]
    
    job_ids = []
    
    # Submit jobs
    print("\n1️⃣ Submitting 3 jobs...")
    async with httpx.AsyncClient() as client:
        for query in queries:
            response = await client.post(
                "http://localhost:3000/api/scrape",
                json={"query": query}
            )
            job_id = response.json()["job_id"]
            job_ids.append(job_id)
            print(f"   Job submitted: {job_id[:8]}... - {query[:40]}...")
    
    # Connect to all WebSockets
    print(f"\n2️⃣ Connecting to all WebSockets...")
    connections = {}
    
    for job_id in job_ids:
        try:
            ws_url = f"ws://localhost:3000/ws/jobs/{job_id}"
            websocket = await websockets.connect(ws_url)
            connections[job_id] = websocket
            print(f"   ✅ Connected to {job_id[:8]}...")
        except Exception as e:
            print(f"   ❌ Failed to connect to {job_id[:8]}...: {e}")
    
    # Listen for updates from all jobs
    print(f"\n3️⃣ Listening for updates from all jobs...")
    print("-" * 60)
    
    completed = 0
    total = len(connections)
    
    while completed < total:
        # Wait for message from any connection
        for job_id, websocket in connections.items():
            try:
                message = await asyncio.wait_for(
                    asyncio.create_task(websocket.recv()),
                    timeout=1.0
                )
                
                data = json.loads(message)
                if data["type"] == "job_update":
                    job = data["job"]
                    status = job["status"]
                    
                    print(f"\n📡 Job {job_id[:8]}... - Status: {status}")
                    
                    if status in ["completed", "failed"]:
                        completed += 1
                        if status == "completed":
                            sources = job.get("result", {}).get("total_sources", 0)
                            print(f"   ✅ Completed! Sources: {sources}")
                        else:
                            print(f"   ❌ Failed: {job.get('error', 'Unknown')}")
            
            except asyncio.TimeoutError:
                continue
            except websockets.exceptions.ConnectionClosed:
                print(f"   🔌 Connection closed for {job_id[:8]}...")
                completed += 1
            except Exception as e:
                print(f"   ⚠️ Error: {e}")
    
    # Close all connections
    print(f"\n4️⃣ Closing all connections...")
    for websocket in connections.values():
        await websocket.close()
    
    print("\n" + "=" * 60)
    print("✅ Multiple WebSocket test completed!")


async def main():
    """Run all WebSocket tests."""
    await test_websocket_updates()
    await test_websocket_multiple_jobs()


if __name__ == "__main__":
    asyncio.run(main())
