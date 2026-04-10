import requests
import json
import time

# Test the Dockerized API
url = "http://localhost:3001/api/scrape"
data = {"query": "What is the distance to the moon?"}

print(f"Sending request to {url}...")
try:
    response = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        json=data,
        timeout=10
    )
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    if response.status_code == 200:
        job_id = response.json().get("id") or response.json().get("job_id")
        print(f"Job ID: {job_id}")
        
        # Poll for result
        for _ in range(30):
            print(f"Polling for result (job {job_id})...")
            res = requests.get(f"http://localhost:3001/api/result/{job_id}")
            result_data = res.json()
            if result_data.get("status") in ["completed", "failed"]:
                print(f"Final Status: {result_data.get('status')}")
                print(f"Result: {json.dumps(result_data, indent=2)}")
                break
            time.sleep(5)
except Exception as e:
    print(f"Error: {e}")
