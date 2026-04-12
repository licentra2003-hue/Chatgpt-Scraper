import requests
import json
import time

# Railway Production API URL
base_url = "https://chatgpt-scraper-api-production.up.railway.app"
scrape_url = f"{base_url}/api/scrape"

# Valid IDs from your Supabase DB for testing
# (Using the same IDs we verified earlier)
product_id = "c47a1130-deaa-48b2-b666-b88adf25e48e"
snapshot_id = "7cba562a-5f7b-4422-9c8f-d30a186f3be5"

data = {
    "query": "What are the latest advancements in AI agents?",
    "product_id": product_id,
    "snapshot_id": snapshot_id
}

print(f"--- Sending request to Railway: {scrape_url}...")
print(f"Product ID: {product_id}")

try:
    # 1. Initiate Scrape
    response = requests.post(
        scrape_url,
        headers={"Content-Type": "application/json"},
        json=data,
        timeout=15
    )
    
    if response.status_code == 201:
        job_id = response.json().get("job_id")
        print(f"OK: Job Created! ID: {job_id}")
        
        # 2. Poll for results from the production server
        print("\nPolling Railway server for results (this may take up to 2 minutes)...")
        
        result_url = f"{base_url}/api/result/{job_id}"
        
        for i in range(60): # 2 minutes (2s delay * 60)
            res = requests.get(result_url)
            
            if res.status_code == 200:
                result_data = res.json()
                status = result_data.get("status")
                
                print(f"   [Attempt {i+1}] Status: {status}")
                
                if status == "completed":
                    print("\nSUCCESS: Scraped data received from Railway.")
                    print("-" * 50)
                    content = result_data.get("result", {}).get("response_text", "")
                    print(f"Response Preview: {content[:200]}...")
                    print("-" * 50)
                    print("Check your Supabase 'product_analysis_chatgpt' table for the persisted record.")
                    break
                elif status == "failed":
                    print(f"\nERROR: Job Failed on Server: {result_data.get('error')}")
                    break
            else:
                print(f"   [Attempt {i+1}] Unexpected status from server: {res.status_code}")
                
            time.sleep(2)
        else:
            print("\nTIMEOUT: The Railway server took too long to respond.")
    
    else:
        print(f"ERROR: Failed to initiate scrape. Status: {response.status_code}")
        print(f"Response: {response.text}")

except Exception as e:
    print(f"ERROR: Error connecting to Railway: {e}")
