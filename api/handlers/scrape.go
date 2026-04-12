package handlers

import (
	"encoding/json"
	"log"
	"net/http"
	"sync"
	"time"

	"scraper-api/models"

	"github.com/gofiber/fiber/v2"
	"github.com/google/uuid"
)

type ScrapeHandler struct {
	db        *Database
	queue     *Queue
	results   map[string]string
	resultsMu sync.RWMutex
}

func NewScrapeHandler(db *Database, queue *Queue) *ScrapeHandler {
	return &ScrapeHandler{
		db:      db,
		queue:   queue,
		results: make(map[string]string),
	}
}

func (h *ScrapeHandler) PostResult(c *fiber.Ctx) error {
	jobID := c.Params("id")
	var payload map[string]any
	if err := c.BodyParser(&payload); err != nil {
		return c.Status(http.StatusBadRequest).JSON(fiber.Map{
			"error": "Invalid request body",
		})
	}

	resultAny, ok := payload["result"]
	if !ok {
		return c.Status(http.StatusBadRequest).JSON(fiber.Map{
			"error": "result field is required",
		})
	}

	resultBytes, err := json.Marshal(resultAny)
	if err != nil {
		return c.Status(http.StatusBadRequest).JSON(fiber.Map{
			"error": "failed to serialize result",
		})
	}
	resultJSON := string(resultBytes)

	h.resultsMu.Lock()
	h.results[jobID] = resultJSON
	h.resultsMu.Unlock()

	log.Printf("Received result for job %s", jobID)

	return c.JSON(fiber.Map{
		"status": "result received",
	})
}

func (h *ScrapeHandler) StreamResult(c *fiber.Ctx) error {
	jobID := c.Params("id")

	c.Set("Content-Type", "text/event-stream")
	c.Set("Cache-Control", "no-cache")
	c.Set("Connection", "keep-alive")

	// Send initial status
	c.WriteString("event: status\ndata: {\"status\":\"pending\"}\n\n")

	// Poll for result and stream.
	// Under concurrency, the DB may show "completed" before the result callback
	// is visible to this API instance. Keep the stream alive with heartbeats and
	// only terminate after an explicit timeout.
	const pollInterval = 1 * time.Second
	const heartbeatInterval = 15 * time.Second
	const maxTotalWait = 12 * time.Minute
	const maxPostCompletionWait = 10 * time.Minute

	start := time.Now()
	lastHeartbeat := time.Now()
	completedAt := time.Time{}
	completedStatusSent := false

	for time.Since(start) < maxTotalWait {
		h.resultsMu.RLock()
		result, exists := h.results[jobID]
		h.resultsMu.RUnlock()

		if exists {
			c.WriteString("event: result\ndata: " + result + "\n\n")
			c.WriteString("event: status\ndata: {\"status\":\"completed\"}\n\n")
			return nil
		}

		// Heartbeat to keep connections alive through proxies / load balancers.
		if time.Since(lastHeartbeat) >= heartbeatInterval {
			c.WriteString("event: ping\ndata: {}\n\n")
			lastHeartbeat = time.Now()
		}

		// Check job status from database
		job, err := h.db.GetJob(uuid.MustParse(jobID))
		if err == nil && job.Status == "completed" {
			if completedAt.IsZero() {
				completedAt = time.Now()
			}
			if !completedStatusSent {
				c.WriteString("event: status\ndata: {\"status\":\"completed\"}\n\n")
				completedStatusSent = true
			}

			// If we're completed but still don't have the in-memory result, wait
			// explicitly for it up to a larger post-completion window.
			if time.Since(completedAt) > maxPostCompletionWait {
				c.WriteString("event: status\ndata: {\"status\":\"timeout\"}\n\n")
				return nil
			}
		}

		time.Sleep(pollInterval)
	}

	c.WriteString("event: status\ndata: {\"status\":\"timeout\"}\n\n")
	return nil
}

func (h *ScrapeHandler) PostScrape(c *fiber.Ctx) error {
	var req models.ScrapeRequest

	if err := c.BodyParser(&req); err != nil {
		return c.Status(http.StatusBadRequest).JSON(fiber.Map{
			"error": "Invalid request body",
		})
	}

	if req.Query == "" {
		return c.Status(http.StatusBadRequest).JSON(fiber.Map{
			"error": "Query is required",
		})
	}

	// Create job in database
	job, err := h.db.CreateJob(req.Query, req.ProductID, req.SnapshotID, req.CallbackURL, req.WorkerID)
	if err != nil {
		log.Printf("Failed to create job: %v", err)
		return c.Status(http.StatusInternalServerError).JSON(fiber.Map{
			"error": "Failed to create job",
		})
	}

	// Publish job to queue
	if err := h.queue.PublishJob(job); err != nil {
		log.Printf("Failed to publish job to queue: %v", err)
		return c.Status(http.StatusInternalServerError).JSON(fiber.Map{
			"error": "Failed to queue job",
		})
	}

	log.Printf("Created and queued job %s for query: %s", job.ID, req.Query)

	return c.Status(http.StatusCreated).JSON(models.ScrapeResponse{
		JobID: job.ID,
	})
}

func (h *ScrapeHandler) GetResult(c *fiber.Ctx) error {
	jobIDStr := c.Params("id")

	jobID, err := uuid.Parse(jobIDStr)
	if err != nil {
		return c.Status(http.StatusBadRequest).JSON(fiber.Map{
			"error": "Invalid job ID format",
		})
	}

	// Get job from database
	job, err := h.db.GetJob(jobID)
	if err != nil {
		if err.Error() == "job not found" {
			return c.Status(http.StatusNotFound).JSON(fiber.Map{
				"error": "Job not found",
			})
		}
		log.Printf("Failed to get job: %v", err)
		return c.Status(http.StatusInternalServerError).JSON(fiber.Map{
			"error": "Failed to get job",
		})
	}

	// If the worker has posted the result back to the API, return it to the caller.
	h.resultsMu.RLock()
	result, exists := h.results[jobIDStr]
	h.resultsMu.RUnlock()
	if exists {
		var resultObj any
		if err := json.Unmarshal([]byte(result), &resultObj); err != nil {
			resultObj = result
		}
		return c.JSON(fiber.Map{
			"id":         job.ID,
			"query":      job.Query,
			"status":     job.Status,
			"created_at": job.CreatedAt,
			"updated_at": job.UpdatedAt,
			"result":     resultObj,
		})
	}

	return c.JSON(job)
}
