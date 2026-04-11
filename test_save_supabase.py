import requests
import json
import time
import uuid

# Test the Dockerized API with Supabase save logic
url = "http://localhost:3001/api/scrape"

# Real IDs for testing (from the DB)
mock_product_id = "c47a1130-deaa-48b2-b666-b88adf25e48e"
mock_snapshot_id = "7cba562a-5f7b-4422-9c8f-d30a186f3be5"

data = {
    "query": "What are the common features of MMPs?",
    "product_id": mock_product_id,
    "snapshot_id": mock_snapshot_id
}

print(f"Sending request to {url}...")
print(f"Product ID: {mock_product_id}")
print(f"Snapshot ID: {mock_snapshot_id}")

try:
    response = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        json=data,
        timeout=10
    )
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    if response.status_code == 201:
        job_id = response.json().get("job_id")
        print(f"Job ID: {job_id}")
        
        # Poll for result
        print("Polling for result (this may take a minute)...")
        for i in range(120): # 2 minutes timeout
            res = requests.get(f"http://localhost:3001/api/result/{job_id}")
            result_data = res.json()
            status = result_data.get("status")
            
            if i % 10 == 0:
                print(f"   [Tick {i}] Full response: {json.dumps(result_data, indent=2)}")
            
            if status == "completed":
                print(f"\nFinal Status: {status}")
                print(f"Result excerpt: {str(result_data.get('result', {}).get('response_text', ''))[:100]}...")
                print("\nTest finished. Check your Supabase 'product_analysis_chatgpt' table for the record.")
                break
            elif status == "failed":
                print(f"\nFinal Status: {status}")
                print(f"Error: {result_data.get('error')}")
                break
            
            time.sleep(2)
    else:
        print("Failed to initiate scrape.")
        
except Exception as e:
    print(f"Error: {e}")
