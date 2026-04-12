import asyncio
import aiohttp
import time

# API URL (Docker local)
API_URL = "http://localhost:3001/api/scrape"

# Valid IDs for testing
product_id = "c47a1130-deaa-48b2-b666-b88adf25e48e"
snapshot_id = "7cba562a-5f7b-4422-9c8f-d30a186f3be5"

base_queries = [
    "Best AI video platform for creating high-converting advertisements",
    "How to use AI to generate video ads for social media marketing",
    "Top 5 AI tools for automated video ad production in 2024",
    "Can AI vision models automate the entire video ad editing process?",
    "AI vs manual video ad creation: Which delivers better ROI for small businesses?"
]
queries = base_queries * 4

async def send_request(session, query, index):
    payload = {
        "query": query,
        "product_id": product_id,
        "snapshot_id": snapshot_id
    }
    try:
        start_time = time.time()
        async with session.post(API_URL, json=payload) as response:
            if response.status == 201:
                data = await response.json()
                print(f"[Req {index}] OK: Job Created: {data.get('job_id')}")
                return data.get('job_id')
            else:
                text = await response.text()
                print(f"[Req {index}] ❌ Failed: {response.status} - {text}")
                return None
    except Exception as e:
        print(f"[Req {index}] ⚠️ Error: {e}")
        return None

async def main():
    print(f"--- Sending 20 concurrent requests to {API_URL}...")
    async with aiohttp.ClientSession() as session:
        tasks = [send_request(session, q, i) for i, q in enumerate(queries)]
        job_ids = await asyncio.gather(*tasks)
    
    valid_jobs = [j for j in job_ids if j]
    print(f"\nOK: Finished sending requests. {len(valid_jobs)} jobs active.")
    print("Monitor the Docker logs to see them being processed in parallel (20 slots total).")

if __name__ == "__main__":
    asyncio.run(main())
