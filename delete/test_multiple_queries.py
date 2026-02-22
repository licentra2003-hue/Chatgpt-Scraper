#!/usr/bin/env python3

import asyncio
import os
import time
from dotenv import load_dotenv
from worker.scraper import BrowserManager, ChatGPTScraper

async def test_multiple_queries():
    """Test scraper with 10 different MMP-related queries"""
    
    print("🚀 Testing Multiple MMP Queries")
    print("=" * 60)
    
    # Load environment variables
    load_dotenv()
    
    # 10 different MMP-related queries
    queries = [
        "What is a Mobile Measurement Platform?",
        "Which MMP platform is best for gaming apps?",
        "How do MMP platforms track user attribution?",
        "What are the top MMP solutions for 2025?",
        "AppsFlyer vs Adjust comparison",
        "How to choose the right MMP for e-commerce?",
        "What are MMP pricing models?",
        "Branch vs Kochava vs Singular",
        "How do MMPs integrate with ad networks?",
        "What are MMP privacy compliance requirements?"
    ]
    
    print(f"📁 Profile Directory: {os.path.join(os.getcwd(), 'test_debug_profile')}")
    print(f"🔧 HEADLESS: {os.environ.get('HEADLESS', 'false')} (Visible Browser)")
    print(f"📝 Testing {len(queries)} different queries...")
    
    # Initialize BrowserManager and Scraper
    print("\n🌐 Initializing Browser Manager...")
    browser_manager = BrowserManager("test_debug_profile")
    
    print("🤖 Initializing ChatGPT Scraper...")
    scraper = ChatGPTScraper()
    
    results = []
    
    try:
        page = await browser_manager.get_page()
        
        for i, query in enumerate(queries, 1):
            print(f"\n{'='*60}")
            print(f"🔍 Test {i}/10: {query}")
            print('='*60)
            
            start_time = time.time()
            
            try:
                result = await scraper.scrape(page, query)
                end_time = time.time()
                duration = round(end_time - start_time, 2)
                
                if result.success:
                    print(f"✅ SUCCESS in {duration}s")
                    print(f"📝 Response: {result.response_text[:100]}...")
                    print(f"📚 Sources: {result.total_sources}")
                    results.append({
                        'test': i,
                        'query': query,
                        'success': True,
                        'duration': duration,
                        'response_length': len(result.response_text),
                        'sources': result.total_sources
                    })
                else:
                    end_time = time.time()
                    duration = round(end_time - start_time, 2)
                    print(f"❌ FAILED in {duration}s")
                    print(f"🚨 Error: {result.error_message}")
                    results.append({
                        'test': i,
                        'query': query,
                        'success': False,
                        'duration': duration,
                        'error': result.error_message
                    })
                
                # Small delay between queries to avoid rate limiting
                await asyncio.sleep(2)
                
            except Exception as e:
                end_time = time.time()
                duration = round(end_time - start_time, 2)
                print(f"💥 EXCEPTION in {duration}s: {e}")
                results.append({
                    'test': i,
                    'query': query,
                    'success': False,
                    'duration': duration,
                    'error': str(e)
                })
        
        print(f"\n{'='*60}")
        print("📊 SUMMARY REPORT")
        print('='*60)
        
        successful = sum(1 for r in results if r['success'])
        failed = len(results) - successful
        
        print(f"✅ Successful: {successful}/{len(results)} ({successful/len(results)*100:.1f}%)")
        print(f"❌ Failed: {failed}/{len(results)} ({failed/len(results)*100:.1f}%)")
        
        if successful > 0:
            avg_duration = sum(r['duration'] for r in results if r['success']) / successful
            avg_response_length = sum(r['response_length'] for r in results if r.get('response_length', 0)) / successful
            avg_sources = sum(r['sources'] for r in results if r.get('sources', 0)) / successful
            
            print(f"⏱️  Avg Duration: {avg_duration:.2f}s")
            print(f"📝 Avg Response Length: {avg_response_length:.0f} chars")
            print(f"📚 Avg Sources: {avg_sources:.1f}")
        
        print(f"\n📋 Detailed Results:")
        for result in results:
            status = "✅" if result['success'] else "❌"
            print(f"{status} Test {result['test']}: {result['duration']}s - {result['query'][:50]}...")
        
    except Exception as e:
        print(f"\n💥 CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        print("\n🧹 Cleaning up...")
        try:
            await browser_manager.close()
            print("✅ Browser stopped")
        except Exception as e:
            print(f"⚠️ Error during cleanup: {e}")

if __name__ == "__main__":
    # Set headless to false for visible browser
    os.environ["HEADLESS"] = "false"
    
    # Run the test
    asyncio.run(test_multiple_queries())
