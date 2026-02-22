-- Create scraping_jobs table in Supabase
CREATE TABLE scraping_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'processing', 'completed', 'failed')) DEFAULT 'pending',
    result_json JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create processed_jobs table for job tracking (status derived from processed_at)
CREATE TABLE processed_jobs (
    job_id VARCHAR PRIMARY KEY,
    engine VARCHAR DEFAULT 'Chatgpt',
    processed_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE
);

-- Create index for better query performance
CREATE INDEX idx_scraping_jobs_status ON scraping_jobs(status);
CREATE INDEX idx_scraping_jobs_created_at ON scraping_jobs(created_at);
CREATE INDEX idx_processed_jobs_processed_at ON processed_jobs(processed_at);

-- Create trigger to automatically update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_scraping_jobs_updated_at 
    BEFORE UPDATE ON scraping_jobs 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();
