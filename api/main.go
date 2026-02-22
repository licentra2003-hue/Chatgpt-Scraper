package main

import (
	"log"
	"os"
	"os/signal"
	"syscall"
	"time"

	"scraper-api/handlers"

	"github.com/gofiber/fiber/v2"
	"github.com/joho/godotenv"
)

func main() {
	// Load environment variables from .env file (if present)
	// Docker Compose env vars will take precedence
	_ = godotenv.Load("../.env")

	// Initialize database
	db, err := handlers.NewDatabase()
	if err != nil {
		log.Fatalf("Failed to initialize database: %v", err)
	}
	defer db.Close()

	// Periodic cleanup of expired processed_jobs rows.
	go func() {
		ticker := time.NewTicker(10 * time.Minute)
		defer ticker.Stop()
		for range ticker.C {
			if err := db.CleanupExpiredJobs(); err != nil {
				log.Printf("CleanupExpiredJobs error: %v", err)
			}
		}
	}()

	// Initialize queue
	queue, err := handlers.NewQueue()
	if err != nil {
		log.Fatalf("Failed to initialize queue: %v", err)
	}
	defer queue.Close()

	// Initialize Fiber app
	app := fiber.New(fiber.Config{
		ErrorHandler: func(c *fiber.Ctx, err error) error {
			code := fiber.StatusInternalServerError
			if e, ok := err.(*fiber.Error); ok {
				code = e.Code
			}
			return c.Status(code).JSON(fiber.Map{
				"error": err.Error(),
			})
		},
	})

	// Initialize handlers
	scrapeHandler := handlers.NewScrapeHandler(db, queue)

	// Setup routes
	api := app.Group("/api")
	api.Post("/scrape", scrapeHandler.PostScrape)
	api.Get("/result/:id", scrapeHandler.GetResult)
	api.Post("/result/:id", scrapeHandler.PostResult)
	api.Get("/stream/:id", scrapeHandler.StreamResult)

	// Health check endpoint
	app.Get("/health", func(c *fiber.Ctx) error {
		return c.JSON(fiber.Map{
			"status":  "ok",
			"service": "scraper-api",
		})
	})

	// Start server
	port := getEnv("PORT", "3000")
	log.Printf("Starting server on port %s", port)

	go func() {
		if err := app.Listen(":" + port); err != nil {
			log.Fatalf("Failed to start server: %v", err)
		}
	}()

	// Graceful shutdown
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	log.Println("Shutting down server...")
	if err := app.Shutdown(); err != nil {
		log.Fatalf("Server shutdown error: %v", err)
	}

	log.Println("Server stopped")
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}
