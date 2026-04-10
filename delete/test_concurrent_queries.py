#!/usr/bin/env python3

import asyncio
import os
import sys
import time
import shutil
from datetime import datetime

# Add worker directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'worker'))

try:
    from scraper import BrowserManager, ChatGPTScraper
except ImportError as e:
    print(f"❌ Error: Could not import 'scraper'. Make sure 'worker/scraper.py' exists.")
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

async def test_single_query(query: str, profiles_dir: str, query_id: int):
    """Test a single query with its own browser profile"""
    start_time = time.time()
    
    print(f"🚀 [Query {query_id}] Starting: {query[:50]}...")
    
    # Create unique profile for each query to avoid conflicts
    unique_profile = os.path.join(profiles_dir, f"concurrent_{query_id}")
    
    try:
        browser_manager = BrowserManager(unique_profile)
        scraper = ChatGPTScraper()
        
        page = await browser_manager.get_page()
        result = await scraper.scrape(page, query)
        
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
        
        await browser_manager.close()
        
        # Clean up the profile directory after successful completion
        try:
            if os.path.exists(unique_profile):
                shutil.rmtree(unique_profile, ignore_errors=True)
                print(f"🗑️  [Query {query_id}] Cleaned up profile: {os.path.basename(unique_profile)}")
        except Exception as e:
            print(f"⚠️  [Query {query_id}] Could not clean up profile: {e}")
        
        return {
            "query_id": query_id,
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
        
        # Clean up the profile directory even on failure
        try:
            if os.path.exists(unique_profile):
                shutil.rmtree(unique_profile, ignore_errors=True)
                print(f"🗑️  [Query {query_id}] Cleaned up profile after failure: {os.path.basename(unique_profile)}")
        except Exception as cleanup_e:
            print(f"⚠️  [Query {query_id}] Could not clean up profile: {cleanup_e}")
        
        return {
            "query_id": query_id,
            "query": query,
            "success": False,
            "response_length": 0,
            "sources_count": 0,
            "elapsed_time": elapsed,
            "error": str(e)
        }

async def test_concurrent_queries():
    """Test multiple queries concurrently"""
    print("🚀 Starting Concurrent Scraper Test...")
    print(f"📊 Testing {len(TEST_QUERIES)} queries simultaneously")
    print(f"⏰ Started at: {datetime.now().strftime('%H:%M:%S')}")
    
    # Create profiles directory if it doesn't exist
    profiles_dir = os.path.join(os.getcwd(), "profiles")
    os.makedirs(profiles_dir, exist_ok=True)
    print(f"📁 Using profiles directory: {profiles_dir}")
    
    # Start all queries concurrently
    start_time = time.time()
    
    tasks = [
        test_single_query(query, profiles_dir, i+1)
        for i, query in enumerate(TEST_QUERIES)
    ]
    
    # Wait for all to complete
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    total_elapsed = time.time() - start_time
    
    # Final cleanup - remove any remaining profile directories
    try:
        if os.path.exists(profiles_dir):
            for item in os.listdir(profiles_dir):
                if item.startswith("concurrent_"):
                    item_path = os.path.join(profiles_dir, item)
                    shutil.rmtree(item_path, ignore_errors=True)
                    print(f"🗑️  Final cleanup: Removed {item}")
    except Exception as e:
        print(f"⚠️  Final cleanup warning: {e}")
    
    # Summary
    print(f"\n{'='*80}")
    print("📊 CONCURRENT TEST SUMMARY")
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
            print(f"  {status} Query {result['query_id']}: {result['elapsed_time']:.2f}s, "
                  f"{result['response_length']} chars, {result['sources_count']} sources")
            if result['error']:
                print(f"     Error: {result['error']}")
        else:
            print(f"  ❌ Exception: {result}")
    
    print(f"\n⏰ Completed at: {datetime.now().strftime('%H:%M:%S')}")
    print(f"🧹 All temporary profiles cleaned up!")

if __name__ == "__main__":
    print("🔧 Concurrent Scraper Test")
    print("This will test 5 queries simultaneously using separate browser profiles")
    print("Each query gets its own browser context to avoid conflicts\n")
    
    # Run the concurrent test
    asyncio.run(test_concurrent_queries())
