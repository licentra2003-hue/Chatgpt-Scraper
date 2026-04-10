package models

import (
	"time"

	"github.com/google/uuid"
)

type ScrapeRequest struct {
	Query string `json:"query"`
}

type Job struct {
	ID         uuid.UUID `json:"id" db:"id"`
	Query      string    `json:"query" db:"query"`
	Status     string    `json:"status" db:"status"`
	ResultJSON *string   `json:"result_json,omitempty" db:"result_json"`
	CreatedAt  time.Time `json:"created_at" db:"created_at"`
	UpdatedAt  time.Time `json:"updated_at" db:"updated_at"`
}

type QueueMessage struct {
	JobID uuid.UUID `json:"job_id"`
	Query string    `json:"query"`
}

type ScrapeResponse struct {
	JobID uuid.UUID `json:"job_id"`
}
