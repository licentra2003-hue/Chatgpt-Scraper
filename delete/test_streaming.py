"""Test SSE streaming for results"""
import requests
import json
import time

def test_streaming():
    api_base_url = "http://localhost:3001"
    
    print("🧪 Testing SSE Streaming\n")
    
    # Step 1: Create job
    print("Step 1: Creating job...")
    response = requests.post(
        f"{api_base_url}/api/scrape",
        json={"query": "What is the capital of France?"}
    )
    
    if response.status_code != 201:
        print(f"❌ Failed to create job: {response.status_code}")
        return False
    
    job_id = response.json().get("job_id")
    print(f"✅ Job created with ID: {job_id}")
    
    # Step 2: Connect to SSE stream
    print("\nStep 2: Connecting to SSE stream...")
    response = requests.get(
        f"{api_base_url}/api/stream/{job_id}",
        stream=True
    )
    
    if response.status_code != 200:
        print(f"❌ Failed to connect to stream: {response.status_code}")
        return False
    
    print("✅ Connected to SSE stream")
    print("\nStep 3: Receiving events...")
    
    # Step 3: Receive events
    for line in response.iter_lines():
        if line:
            line = line.decode('utf-8')
            if line.startswith('data:'):
                data = line.replace('data:', '').strip()
                try:
                    parsed = json.loads(data)
                    event_type = parsed.get('type', 'unknown')
                    print(f"📨 Event: {event_type}")
                    
                    if 'status' in parsed:
                        print(f"   Status: {parsed['status']}")
                    
                    if 'result' in parsed:
                        print(f"   Result: {parsed['result'][:200]}...")
                        
                    if parsed.get('status') == 'completed':
                        print("\n✅ Streaming test passed!")
                        return True
                        
                except json.JSONDecodeError:
                    print(f"   Raw data: {data}")
    
    print("\n❌ Streaming test failed - no completion event received")
    return False

if __name__ == "__main__":
    test_streaming()
