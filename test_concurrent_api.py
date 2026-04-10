#!/usr/bin/env python3
"""
Concurrent API Test - Tests multiple simultaneous API requests
Tests the full flow: POST /api/scrape -> GET /api/stream/:id (SSE)
"""

import asyncio
import aiohttp
import json
import time
from datetime import datetime
from typing import Dict, Any

API_BASE_URL = "http://localhost:3001"

# When True, runs the sequential test after the concurrent test.
RUN_SEQUENTIAL_AFTER_CONCURRENT = False

# Test queries for concurrent execution
TEST_QUERIES = [
    "What is a Mobile Measurement Platform?",
    "Which MMP platform is best for gaming apps?",
    "AppsFlyer vs Adjust comparison",
    "What are MMP pricing models?",
    "How to choose the right MMP for e-commerce?"
]


async def submit_job(session: aiohttp.ClientSession, query: str, query_id: int) -> Dict[str, Any]:
    """Submit a job and stream results via SSE"""
    start_time = time.time()
    print(f"🚀 [Query {query_id}] Submitting: {query[:50]}...")

    try:
        # Step 1: POST /api/scrape
        async with session.post(
            f"{API_BASE_URL}/api/scrape",
            json={"query": query},
            headers={"Content-Type": "application/json"}
        ) as response:
            if response.status != 201:
                raise Exception(f"Failed to submit job: {response.status}")

            job_data = await response.json()
            job_id = job_data["job_id"]
            print(f"📝 [Query {query_id}] Job ID: {job_id}")

        # Step 2: GET /api/stream/:id (SSE)
        result_data = None
        status_data = None
        received_result = False

        async with session.get(
            f"{API_BASE_URL}/api/stream/{job_id}",
            headers={"Accept": "text/event-stream"}
        ) as response:
            if response.status != 200:
                raise Exception(f"Failed to open stream: {response.status}")

            # Parse SSE events
            current_event = None
            async for line in response.content:
                line = line.decode('utf-8').strip()
                
                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    if current_event:
                        data_json = line.split(":", 1)[1].strip()
                        try:
                            data = json.loads(data_json)
                            
                            if current_event == "status":
                                status_data = data
                                print(f"📊 [Query {query_id}] Status: {data.get('status')}")
                            
                            elif current_event == "result":
                                result_data = data
                                received_result = True
                                print(f"✅ [Query {query_id}] Result received")
                                # Break after receiving result
                                break
                        except json.JSONDecodeError:
                            pass
                    current_event = None

        # Fallback: if SSE ended without a result, poll /api/result/:id for a while.
        # This avoids NoneType failures and makes the test resilient to stream drops.
        if not received_result:
            poll_start = time.time()
            poll_timeout = 180  # seconds
            while time.time() - poll_start < poll_timeout:
                try:
                    async with session.get(f"{API_BASE_URL}/api/result/{job_id}") as r:
                        if r.status == 200:
                            body = await r.json()
                            maybe_result = body.get("result") if isinstance(body, dict) else None
                            if maybe_result is not None:
                                result_data = maybe_result
                                received_result = True
                                print(f"✅ [Query {query_id}] Result received (poll fallback)")
                                break
                except Exception:
                    pass
                await asyncio.sleep(2)

        elapsed = time.time() - start_time

        # Summary
        print(f"\n{'='*60}")
        print(f"✅ [Query {query_id}] COMPLETED in {elapsed:.2f}s")
        print(f"{'='*60}")
        
        if result_data:
            print(f"Query: {result_data.get('query')}")
            print(f"Success: {result_data.get('success')}")
            print(f"Response Length: {len(result_data.get('response_text', ''))} chars")
            print(f"Sources Found: {result_data.get('total_sources', 0)}")
            
            if result_data.get('response_text'):
                preview = result_data['response_text'][:200] + "..." if len(result_data['response_text']) > 200 else result_data['response_text']
                print(f"Response Preview: {preview}")
            
            if result_data.get('source_links'):
                print(f"First 3 Sources:")
                for i, source in enumerate(result_data['source_links'][:3]):
                    print(f"  {i+1}. {source.get('title', 'N/A')[:60]}...")
        
        if result_data and result_data.get('error_message'):
            print(f"Error: {result_data['error_message']}")

        return {
            "query_id": query_id,
            "query": query,
            "job_id": job_id,
            "success": result_data.get('success', False) if result_data else False,
            "response_length": len(result_data.get('response_text', '')) if result_data else 0,
            "sources_count": result_data.get('total_sources', 0) if result_data else 0,
            "elapsed_time": elapsed,
            "error": result_data.get('error_message') if result_data else "No result received"
        }

    except Exception as e:
        elapsed = time.time() - start_time
        print(f"❌ [Query {query_id}] FAILED after {elapsed:.2f}s: {e}")
        return {
            "query_id": query_id,
            "query": query,
            "job_id": None,
            "success": False,
            "response_length": 0,
            "sources_count": 0,
            "elapsed_time": elapsed,
            "error": str(e)
        }


async def test_concurrent_api():
    """Test multiple concurrent API requests"""
    print("🚀 Starting Concurrent API Test...")
    print(f"📊 Testing {len(TEST_QUERIES)} queries simultaneously")
    print(f"⏰ Started at: {datetime.now().strftime('%H:%M:%S')}")
    print(f"🌐 API URL: {API_BASE_URL}\n")

    start_time = time.time()

    # Create HTTP session
    async with aiohttp.ClientSession() as session:
        # Submit all jobs concurrently
        tasks = [
            submit_job(session, query, i + 1)
            for i, query in enumerate(TEST_QUERIES)
        ]

        # Wait for all to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

    total_elapsed = time.time() - start_time

    # Summary
    print(f"\n{'='*80}")
    print("📊 CONCURRENT API TEST SUMMARY")
    print(f"{'='*80}")
    print(f"Total Time: {total_elapsed:.2f}s")
    print(f"Queries Run: {len(TEST_QUERIES)}")

    successful = sum(1 for r in results if isinstance(r, dict) and r.get('success', False))
    failed = len(results) - successful

    print(f"✅ Successful: {successful}")
    print(f"❌ Failed: {failed}")

    if successful > 0:
        avg_time = sum(r['elapsed_time'] for r in results if isinstance(r, dict) and r.get('success', False)) / successful
        print(f"⏱️  Average Time per Query: {avg_time:.2f}s")
        print(f"🚀 Time Saved (vs sequential): {(len(TEST_QUERIES) * avg_time) - total_elapsed:.2f}s")
        print(f"📈 Throughput: {successful / total_elapsed:.2f} queries/second")

    print(f"\n📋 Detailed Results:")
    for result in results:
        if isinstance(result, dict):
            status = "✅" if result['success'] else "❌"
            print(f"  {status} Query {result['query_id']}: {result['elapsed_time']:.2f}s, "
                  f"{result['response_length']} chars, {result['sources_count']} sources")
            if result.get('error'):
                print(f"     Error: {result['error']}")
            if result.get('job_id'):
                print(f"     Job ID: {result['job_id']}")
        else:
            print(f"  ❌ Exception: {result}")

    print(f"\n⏰ Completed at: {datetime.now().strftime('%H:%M:%S')}")


async def test_sequential_api():
    """Test sequential API requests for comparison"""
    print("\n" + "=" * 80)
    print("🔄 Running Sequential API Test for Comparison...")
    print("=" * 80)

    start_time = time.time()

    async with aiohttp.ClientSession() as session:
        for i, query in enumerate(TEST_QUERIES, 1):
            result = await submit_job(session, query, i)

    total_elapsed = time.time() - start_time

    print(f"\n{'='*80}")
    print("📊 SEQUENTIAL API TEST SUMMARY")
    print(f"{'='*80}")
    print(f"Total Time: {total_elapsed:.2f}s")
    print(f"Queries Run: {len(TEST_QUERIES)}")


async def main():
    """Run both concurrent and sequential tests"""
    print("🧪 Concurrent vs Sequential API Test")
    print("=" * 80)
    print("This will test 5 queries:")
    print("  1. Concurrently (all at once)")
    print("  2. Sequentially (one after another)")
    print("=" * 80 + "\n")

    # Run concurrent test
    await test_concurrent_api()

    # Run sequential test for comparison (opt-in)
    if RUN_SEQUENTIAL_AFTER_CONCURRENT:
        await test_sequential_api()


if __name__ == "__main__":
    asyncio.run(main())
