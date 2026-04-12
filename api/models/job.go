package models

import (
	"time"

	"github.com/google/uuid"
)

type ScrapeRequest struct {
	Query      string  `json:"query"`
	ProductID   *string `json:"product_id,omitempty"`
	SnapshotID  *string `json:"snapshot_id,omitempty"`
	CallbackURL *string `json:"callback_url,omitempty"`
	WorkerID    *string `json:"worker_id,omitempty"`
}

type Job struct {
	ID         uuid.UUID `json:"id" db:"id"`
	Query      string    `json:"query" db:"query"`
	Status     string    `json:"status" db:"status"`
	ResultJSON *string   `json:"result_json,omitempty" db:"result_json"`
	CreatedAt  time.Time `json:"created_at" db:"created_at"`
	UpdatedAt  time.Time `json:"updated_at" db:"updated_at"`
	ProductID   *string   `json:"product_id,omitempty"`
	SnapshotID  *string   `json:"snapshot_id,omitempty"`
	CallbackURL *string   `json:"callback_url,omitempty"`
	WorkerID    *string   `json:"worker_id,omitempty"`
}

type QueueMessage struct {
	JobID      uuid.UUID `json:"job_id"`
	Query      string    `json:"query"`
	ProductID   *string   `json:"product_id,omitempty"`
	SnapshotID  *string   `json:"snapshot_id,omitempty"`
	CallbackURL *string   `json:"callback_url,omitempty"`
	WorkerID    *string   `json:"worker_id,omitempty"`
}

type ScrapeResponse struct {
	JobID uuid.UUID `json:"job_id"`
}
