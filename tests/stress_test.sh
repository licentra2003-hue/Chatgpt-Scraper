#!/bin/bash

# Stress Test Script for Polyglot Scraper System
# Fires 20 concurrent requests to the Go API and waits for completion

set -e

# Configuration
API_URL="${API_URL:-http://localhost:3000}"
NUM_REQUESTS=20
TIMEOUT=300  # 5 minutes timeout for all requests
SUPABASE_URL="${SUPABASE_URL:-mock://localhost}"
SUPABASE_KEY="${SUPABASE_KEY:-mock_key}"

echo "🚀 Starting Stress Test: $NUM_REQUESTS concurrent requests"
echo "📍 API URL: $API_URL"
echo "⏱️  Timeout: ${TIMEOUT}s"
echo ""

# Check if API is running
echo "🔍 Checking API health..."
if ! curl -s "$API_URL/health" > /dev/null; then
    echo "❌ API is not responding at $API_URL"
    echo "💡 Make sure the system is running: docker-compose up -d"
    exit 1
fi
echo "✅ API is healthy"

# Function to send a single request
send_request() {
    local request_id=$1
    local query="Test query $request_id: What is the meaning of life?"
    
    response=$(curl -s -X POST \
        -H "Content-Type: application/json" \
        -d "{\"query\":\"$query\"}" \
        "$API_URL/scrape")
    
    job_id=$(echo "$response" | grep -o '"job_id":"[^"]*"' | cut -d'"' -f4)
    
    if [ -n "$job_id" ]; then
        echo "📤 Request $request_id: Job ID $job_id"
        echo "$job_id"
    else
        echo "❌ Request $request_id: Failed to get job ID"
        echo "Response: $response"
        exit 1
    fi
}

# Function to check job status
check_job_status() {
    local job_id=$1
    
    response=$(curl -s "$API_URL/result/$job_id")
    status=$(echo "$response" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
    
    echo "$status"
}

# Send all requests concurrently
echo ""
echo "📨 Sending $NUM_REQUESTS concurrent requests..."

job_ids=()
pids=()

# Send requests in background
for i in $(seq 1 $NUM_REQUESTS); do
    send_request $i &
    pids+=($!)
done

# Collect all job IDs
for pid in "${pids[@]}"; do
    wait $pid
    job_id=$(send_request $i)
    job_ids+=("$job_id")
done

echo "✅ All requests sent. Job IDs: ${#job_ids[@]}"

# Wait for all jobs to complete
echo ""
echo "⏳ Waiting for all jobs to complete..."

start_time=$(date +%s)
completed_jobs=0
failed_jobs=0

while [ $completed_jobs -lt $NUM_REQUESTS ]; do
    current_time=$(date +%s)
    elapsed=$((current_time - start_time))
    
    if [ $elapsed -gt $TIMEOUT ]; then
        echo "❌ Timeout after ${TIMEOUT}s"
        echo "📊 Progress: $completed_jobs/$NUM_REQUESTS completed"
        break
    fi
    
    completed_jobs=0
    failed_jobs=0
    pending_jobs=0
    
    for job_id in "${job_ids[@]}"; do
        status=$(check_job_status "$job_id")
        
        case $status in
            "completed")
                ((completed_jobs++))
                ;;
            "failed")
                ((failed_jobs++))
                ((completed_jobs++))  # Count failed as completed for tracking
                ;;
            "processing")
                ((pending_jobs++))
                ;;
        esac
    done
    
    echo "📊 Progress: $completed_jobs/$NUM_REQUESTS completed | $failed_jobs failed | $pending_jobs pending (${elapsed}s elapsed)"
    
    if [ $completed_jobs -lt $NUM_REQUESTS ]; then
        sleep 5
    fi
done

# Final results
echo ""
echo "🎯 Stress Test Results:"
echo "✅ Completed: $completed_jobs/$NUM_REQUESTS"
echo "❌ Failed: $failed_jobs/$NUM_REQUESTS"
echo "⏱️  Total time: $(($(date +%s) - start_time))s"

# Show sample results
echo ""
echo "📋 Sample Results:"
sample_count=0
for job_id in "${job_ids[@]}"; do
    if [ $sample_count -ge 5 ]; then
        break
    fi
    
    response=$(curl -s "$API_URL/result/$job_id")
    status=$(echo "$response" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
    
    if [ "$status" = "completed" ]; then
        response_text=$(echo "$response" | grep -o '"response_text":"[^"]*"' | cut -d'"' -f4 | head -c 100)
        echo "✅ Job $job_id: $status - ${response_text}..."
    else
        error=$(echo "$response" | grep -o '"error":"[^"]*"' | cut -d'"' -f4 | head -c 100)
        echo "❌ Job $job_id: $status - ${error:-No error details}..."
    fi
    
    ((sample_count++))
done

# Overall assessment
if [ $completed_jobs -eq $NUM_REQUESTS ]; then
    echo ""
    echo "🎉 SUCCESS: All $NUM_REQUESTS requests completed!"
    exit 0
else
    echo ""
    echo "⚠️  PARTIAL: $((NUM_REQUESTS - completed_jobs)) requests did not complete within timeout"
    exit 1
fi
