package handlers

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"scraper-api/models"

	"github.com/google/uuid"
	"github.com/joho/godotenv"
	_ "github.com/lib/pq"
)

type Database struct {
	db      *sql.DB
	restURL string
	restKey string
}

func (d *Database) CleanupExpiredJobs() error {
	// If we're using Supabase REST
	if d.db == nil {
		if d.restURL == "" {
			return nil
		}

		// Supabase expects RFC3339-ish timestamps in query filters.
		now := time.Now().UTC().Format(time.RFC3339Nano)
		resp, err := d.restRequest("DELETE", "/processed_jobs?expires_at=lt."+now, nil)
		if err != nil {
			return fmt.Errorf("failed to cleanup expired jobs via Supabase REST: %w", err)
		}
		defer resp.Body.Close()
		if resp.StatusCode < 200 || resp.StatusCode >= 300 {
			b, _ := io.ReadAll(resp.Body)
			return fmt.Errorf("failed to cleanup expired jobs via Supabase REST: status=%d body=%s", resp.StatusCode, string(b))
		}
		return nil
	}

	// Direct Postgres mode
	querySQL := `DELETE FROM processed_jobs
				 WHERE expires_at IS NOT NULL AND expires_at < NOW()`
	_, err := d.db.Exec(querySQL)
	if err != nil {
		return fmt.Errorf("failed to cleanup expired jobs: %w", err)
	}
	return nil
}

func NewDatabase() (*Database, error) {
	// Load environment variables
	if err := godotenv.Load("../.env"); err != nil {
		log.Println("Warning: Could not load .env file")
	}

	// Supabase settings
	supabaseURL := getEnv("SUPABASE_URL", "")
	supabaseKey := getEnv("SUPABASE_KEY", "")

	// For testing purposes, if Supabase URL is placeholder or mock, create a mock database
	if supabaseURL == "your_supabase_url_here" || supabaseURL == "" || supabaseURL == "mock://localhost" {
		log.Println("Warning: Using mock database - please update SUPABASE_URL in .env")
		return &Database{db: nil, restURL: "", restKey: ""}, nil
	}

	// If SUPABASE_URL is an https URL, use Supabase PostgREST
	if strings.HasPrefix(supabaseURL, "http://") || strings.HasPrefix(supabaseURL, "https://") {
		restBase := strings.TrimRight(supabaseURL, "/") + "/rest/v1"
		if supabaseKey == "" {
			return nil, fmt.Errorf("SUPABASE_KEY is required when using SUPABASE_URL as https URL")
		}
		return &Database{db: nil, restURL: restBase, restKey: supabaseKey}, nil
	}

	// Otherwise, treat SUPABASE_URL as a PostgreSQL connection string
	connStr := fmt.Sprintf("%s?sslmode=require", supabaseURL)

	db, err := sql.Open("postgres", connStr)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to database: %w", err)
	}

	// Test connection
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := db.PingContext(ctx); err != nil {
		return nil, fmt.Errorf("failed to ping database: %w", err)
	}

	return &Database{db: db, restURL: "", restKey: ""}, nil
}

func (d *Database) restRequest(method string, path string, body any) (*http.Response, error) {
	var r io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		r = bytes.NewReader(b)
	}

	req, err := http.NewRequest(method, d.restURL+path, r)
	if err != nil {
		return nil, err
	}
	req.Header.Set("apikey", d.restKey)
	req.Header.Set("Authorization", "Bearer "+d.restKey)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")

	return http.DefaultClient.Do(req)
}

func (d *Database) CreateJob(query string) (*models.Job, error) {
	// Mock database implementation
	if d.db == nil {
		if d.restURL != "" {
			jobID := uuid.New()
			expiresAt := time.Now().Add(24 * time.Hour).Format(time.RFC3339Nano)
			payload := map[string]any{
				"job_id":     jobID.String(),
				"engine":     "Chatgpt",
				"expires_at": expiresAt,
			}

			resp, err := d.restRequest("POST", "/processed_jobs", payload)
			if err != nil {
				return nil, fmt.Errorf("failed to create job via Supabase REST: %w", err)
			}
			defer resp.Body.Close()
			if resp.StatusCode < 200 || resp.StatusCode >= 300 {
				b, _ := io.ReadAll(resp.Body)
				return nil, fmt.Errorf("failed to create job via Supabase REST: status=%d body=%s", resp.StatusCode, string(b))
			}

			return &models.Job{
				ID:        jobID,
				Query:     query,
				Status:    "pending",
				CreatedAt: time.Now(),
				UpdatedAt: time.Now(),
			}, nil
		}

		log.Printf("MOCK: Creating job with query: %s", query)
		job := &models.Job{
			ID:        uuid.New(),
			Query:     query,
			Status:    "pending",
			CreatedAt: time.Now(),
			UpdatedAt: time.Now(),
		}
		log.Printf("MOCK: Created job %s", job.ID)
		return job, nil
	}

	jobID := uuid.New()
	expiresAt := time.Now().Add(24 * time.Hour)

	// Store into processed_jobs tracking table. Note: schema uses job_id (varchar) not uuid id.
	querySQL := `INSERT INTO processed_jobs (job_id, engine, expires_at)
				 VALUES ($1, $2, $3)`

	_, err := d.db.Exec(querySQL, jobID.String(), "Chatgpt", expiresAt)

	if err != nil {
		return nil, fmt.Errorf("failed to create job: %w", err)
	}

	return &models.Job{
		ID:        jobID,
		Query:     query,
		Status:    "pending",
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
	}, nil
}

func (d *Database) GetJob(jobID uuid.UUID) (*models.Job, error) {
	// Mock database implementation
	if d.db == nil {
		if d.restURL != "" {
			resp, err := d.restRequest("GET", "/processed_jobs?select=job_id,processed_at,expires_at,engine&job_id=eq."+jobID.String(), nil)
			if err != nil {
				return nil, fmt.Errorf("failed to get job via Supabase REST: %w", err)
			}
			defer resp.Body.Close()
			if resp.StatusCode == 404 {
				return nil, fmt.Errorf("job not found")
			}
			if resp.StatusCode < 200 || resp.StatusCode >= 300 {
				b, _ := io.ReadAll(resp.Body)
				return nil, fmt.Errorf("failed to get job via Supabase REST: status=%d body=%s", resp.StatusCode, string(b))
			}

			var rows []map[string]any
			if err := json.NewDecoder(resp.Body).Decode(&rows); err != nil {
				return nil, fmt.Errorf("failed to decode Supabase REST response: %w", err)
			}
			if len(rows) == 0 {
				return nil, fmt.Errorf("job not found")
			}

			status := "pending"
			if rows[0]["processed_at"] != nil {
				status = "completed"
			}

			updatedAt := time.Now()
			if processedAtStr, ok := rows[0]["processed_at"].(string); ok {
				if t, err := time.Parse(time.RFC3339Nano, processedAtStr); err == nil {
					updatedAt = t
				}
			}

			return &models.Job{
				ID:         jobID,
				Query:      "",
				Status:     status,
				ResultJSON: nil,
				CreatedAt:  time.Now(),
				UpdatedAt:  updatedAt,
			}, nil
		}

		log.Printf("MOCK: Getting job %s", jobID)
		// Return a mock job for testing
		job := &models.Job{
			ID:        jobID,
			Query:     "mock query",
			Status:    "pending",
			CreatedAt: time.Now(),
			UpdatedAt: time.Now(),
		}
		log.Printf("MOCK: Returning job %s with status %s", job.ID, job.Status)
		return job, nil
	}

	querySQL := `SELECT processed_at, expires_at, engine
				 FROM processed_jobs
				 WHERE job_id = $1`

	var processedAt sql.NullTime
	var expiresAt sql.NullTime
	var engine sql.NullString

	err := d.db.QueryRow(querySQL, jobID.String()).Scan(&processedAt, &expiresAt, &engine)

	if err != nil {
		if err == sql.ErrNoRows {
			return nil, fmt.Errorf("job not found")
		}
		return nil, fmt.Errorf("failed to get job: %w", err)
	}

	status := "pending"
	if processedAt.Valid {
		status = "completed"
	}

	createdAt := time.Now()
	updatedAt := time.Now()
	if processedAt.Valid {
		updatedAt = processedAt.Time
	}

	return &models.Job{
		ID:         jobID,
		Query:      "",
		Status:     status,
		ResultJSON: nil,
		CreatedAt:  createdAt,
		UpdatedAt:  updatedAt,
	}, nil
}

func (d *Database) Close() error {
	if d.db != nil {
		return d.db.Close()
	}
	return nil
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}
