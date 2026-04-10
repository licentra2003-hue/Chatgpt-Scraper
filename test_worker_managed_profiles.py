#!/usr/bin/env python3

import asyncio
import os
import sys
import time
import uuid
from datetime import datetime

# Add worker directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'worker'))

try:
    from scraper import ProfileManager, ManagedChatGPTScraper
except ImportError as e:
    print(f"❌ Error: Could not import scraper components. Make sure 'worker/scraper.py' exists.")
    print(f"Import error: {e}")
    sys.exit(1)

# Test queries for concurrent execution
TEST_QUERIES = [
    "What is the best MMP platform for mobile apps?",
    "How does mobile attribution work with MMPs?",
    "What are the key features of Appsflyer vs Branch?",
    "Which MMP has the best fraud detection capabilities?",
    "What are the pricing models for mobile measurement partners?"
]

async def test_single_query(query: str, profile_manager: ProfileManager, query_id: int):
    """Test a single query using worker-managed profiles"""
    start_time = time.time()
    job_id = f"job_{query_id}_{uuid.uuid4().hex[:8]}"
    
    print(f"🚀 [Query {query_id}] Starting: {query[:50]}...")
    print(f"   📋 Job ID: {job_id}")
    
    try:
        # Use the managed scraper - worker handles profile creation/cleanup
        async with ManagedChatGPTScraper(profile_manager, job_id) as scraper:
            result = await scraper.scrape(query)
        
        elapsed = time.time() - start_time
        
        print(f"\n{'='*60}")
        print(f"✅ [Query {query_id}] COMPLETED in {elapsed:.2f}s")
        print(f"{'='*60}")
        print(f"Query: {result.query}")
        print(f"Success: {result.success}")
        print(f"Response Length: {len(result.response_text)} chars")
        print(f"Sources Found: {result.total_sources}")
        
        if result.error_message:
            print(f"Error: {result.error_message}")
        
        # Show preview of response
        if result.response_text:
            preview = result.response_text[:200] + "..." if len(result.response_text) > 200 else result.response_text
            print(f"Response Preview: {preview}")
        
        # Show first few sources
        if result.source_links:
            print(f"First 3 Sources:")
            for i, source in enumerate(result.source_links[:3]):
                print(f"  {i+1}. {source.title[:60]}...")
        
        return {
            "query_id": query_id,
            "job_id": job_id,
            "query": query,
            "success": result.success,
            "response_length": len(result.response_text),
            "sources_count": result.total_sources,
            "elapsed_time": elapsed,
            "error": result.error_message
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"❌ [Query {query_id}] FAILED after {elapsed:.2f}s: {e}")
        
        return {
            "query_id": query_id,
            "job_id": job_id,
            "query": query,
            "success": False,
            "response_length": 0,
            "sources_count": 0,
            "elapsed_time": elapsed,
            "error": str(e)
        }

async def test_worker_managed_profiles():
    """Test multiple queries using worker-managed profiles"""
    print("🚀 Starting Worker-Managed Profile Test...")
    print(f"📊 Testing {len(TEST_QUERIES)} queries simultaneously")
    print(f"⏰ Started at: {datetime.now().strftime('%H:%M:%S')}")
    
    # Initialize profile manager - worker handles profile directory
    profile_manager = ProfileManager()
    print(f"📁 Profile manager initialized: {profile_manager.base_profiles_dir}")
    
    # Start all queries concurrently
    start_time = time.time()
    
    tasks = [
        test_single_query(query, profile_manager, i+1)
        for i, query in enumerate(TEST_QUERIES)
    ]
    
    # Wait for all to complete
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    total_elapsed = time.time() - start_time
    
    # Final cleanup - worker handles any remaining profiles
    await profile_manager.cleanup_all_temp_profiles()
    
    # Summary
    print(f"\n{'='*80}")
    print("📊 WORKER-MANAGED PROFILE TEST SUMMARY")
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
    
    print(f"\n📋 Detailed Results:")
    for result in results:
        if isinstance(result, dict):
            status = "✅" if result['success'] else "❌"
            print(f"  {status} Query {result['query_id']} ({result['job_id']}): {result['elapsed_time']:.2f}s, "
                  f"{result['response_length']} chars, {result['sources_count']} sources")
            if result['error']:
                print(f"     Error: {result['error']}")
        else:
            print(f"  ❌ Exception: {result}")
    
    print(f"\n⏰ Completed at: {datetime.now().strftime('%H:%M:%S')}")
    print(f"🧹 All profiles managed and cleaned up by worker!")

if __name__ == "__main__":
    print("🔧 Worker-Managed Profile Test")
    print("This will test 5 queries simultaneously using worker-managed browser profiles")
    print("The worker handles profile creation and deletion automatically\n")
    
    # Run the worker-managed test
    asyncio.run(test_worker_managed_profiles())
