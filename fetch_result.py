"""Fetch result via SSE streaming"""
import requests
import json
import time

def fetch_result():
    api_base_url = "http://localhost:3001"
    
    print("🔍 Fetching Result via SSE\n")
    
    # Step 1: Create job
    print("Step 1: Creating job...")
    response = requests.post(
        f"{api_base_url}/api/scrape",
        json={"query": "Top 10 MMP platform in India?"}
    )
    
    if response.status_code != 201:
        print(f"❌ Failed to create job: {response.status_code}")
        return
    
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
        return
    
    print("✅ Connected to SSE stream\n")
    print("Step 3: Receiving events...\n")
    
    # Step 3: Receive events (proper SSE parsing)
    current_event = None
    result_received = False
    completed_seen = False

    for raw in response.iter_lines():
        if raw is None:
            continue

        line = raw.decode("utf-8")
        if not line:
            # blank line separates events
            continue

        if line.startswith("event:"):
            current_event = line[len("event:"):].strip()
            continue

        if not line.startswith("data:"):
            continue

        data = line[len("data:"):].strip()

        # status event payload is JSON like {"status":"pending"}
        if current_event == "status":
            try:
                parsed = json.loads(data)
                status = parsed.get("status")
                print(f"📊 Status: {status}")
                if status == "completed":
                    completed_seen = True
            except json.JSONDecodeError:
                print(f"📊 Status (raw): {data}")
            continue

        # result event payload is JSON (the actual scraped result)
        if current_event == "result":
            try:
                parsed = json.loads(data)
                print("\n📝 Result JSON:")
                print(json.dumps(parsed, indent=2)[:4000])
            except json.JSONDecodeError:
                print("\n📝 Result (raw):")
                print(data[:4000])
            result_received = True
            break

        # Fallback: try to parse any other event as JSON and show it
        try:
            parsed = json.loads(data)
            print(f"📨 Event {current_event}: {parsed}")
        except json.JSONDecodeError:
            print(f"📨 Event {current_event} (raw): {data}")

        # If we saw completed but no result yet, keep waiting (server now waits too)
        if completed_seen:
            continue

    if not result_received:
        print("\n⚠️  No result event received.")
        print("If you only see status=completed, the worker callback may not be posting results.")

if __name__ == "__main__":
    fetch_result()
