#!/usr/bin/env python3
"""
Check processed_jobs table in Supabase
"""

import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Error: SUPABASE_URL and SUPABASE_KEY must be set in .env")
    exit(1)

client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Get all rows from processed_jobs
result = client.table("processed_jobs").select("*").execute()

print(f"📊 Total rows in processed_jobs: {len(result.data)}")
print(f"{'='*80}")

if len(result.data) == 0:
    print("No rows found in processed_jobs table")
else:
    print(f"{'Job ID':<40} {'Engine':<10} {'Processed At':<25} {'Expires At':<25}")
    print(f"{'-'*80}")
    
    for row in result.data:
        job_id = row.get('job_id', 'N/A')
        engine = row.get('engine', 'N/A')
        processed_at = row.get('processed_at', 'N/A')
        expires_at = row.get('expires_at', 'N/A')
        
        # Truncate long values
        job_id = job_id[:37] + '...' if len(job_id) > 37 else job_id
        processed_at = processed_at[:23] + '...' if processed_at and len(processed_at) > 23 else processed_at
        expires_at = expires_at[:23] + '...' if expires_at and len(expires_at) > 23 else expires_at
        
        print(f"{job_id:<40} {engine:<10} {str(processed_at):<25} {str(expires_at):<25}")

print(f"{'='*80}")
