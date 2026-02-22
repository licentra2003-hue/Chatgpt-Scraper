package handlers

import (
	"encoding/json"
	"fmt"
	"log"
	"os"

	"scraper-api/models"

	"github.com/streadway/amqp"
)

type Queue struct {
	conn    *amqp.Connection
	channel *amqp.Channel
}

func NewQueue() (*Queue, error) {
	// Get RabbitMQ URL from environment - MUST be set
	rabbitMQURL := os.Getenv("RABBITMQ_URL")
	if rabbitMQURL == "" {
		return nil, fmt.Errorf("RABBITMQ_URL environment variable is not set")
	}

	log.Printf("🔌 Connecting to RabbitMQ at: %s", rabbitMQURL)

	conn, err := amqp.Dial(rabbitMQURL)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to RabbitMQ: %w", err)
	}

	log.Printf("✅ Connected to RabbitMQ successfully")

	log.Printf("✅ Connected to RabbitMQ successfully")

	ch, err := conn.Channel()
	if err != nil {
		return nil, fmt.Errorf("failed to open a channel: %w", err)
	}

	// Declare queue
	q, err := ch.QueueDeclare(
		"scraping_tasks", // name
		true,             // durable
		false,            // delete when unused
		false,            // exclusive
		false,            // no-wait
		nil,              // arguments
	)
	if err != nil {
		return nil, fmt.Errorf("failed to declare a queue: %w", err)
	}

	log.Printf("Queue declared: %s, messages: %d", q.Name, q.Messages)

	return &Queue{
		conn:    conn,
		channel: ch,
	}, nil
}

func (q *Queue) PublishJob(job *models.Job) error {
	message := models.QueueMessage{
		JobID: job.ID,
		Query: job.Query,
	}

	body, err := json.Marshal(message)
	if err != nil {
		return fmt.Errorf("failed to marshal message: %w", err)
	}

	err = q.channel.Publish(
		"",               // exchange
		"scraping_tasks", // routing key
		false,            // mandatory
		false,            // immediate
		amqp.Publishing{
			ContentType:  "application/json",
			Body:         body,
			DeliveryMode: amqp.Persistent, // make message persistent
		},
	)

	if err != nil {
		return fmt.Errorf("failed to publish message: %w", err)
	}

	log.Printf("Published job %s to queue", job.ID)
	return nil
}

func (q *Queue) GetQueueInfo() (int, error) {
	// Get queue info to check message count
	qInfo, err := q.channel.QueueDeclare(
		"scraping_tasks", // name
		true,             // durable
		false,            // delete when unused
		false,            // exclusive
		false,            // no-wait
		nil,              // arguments
	)
	if err != nil {
		return 0, fmt.Errorf("failed to get queue info: %w", err)
	}

	return qInfo.Messages, nil
}

func (q *Queue) Close() error {
	if q.channel != nil {
		q.channel.Close()
	}
	if q.conn != nil {
		q.conn.Close()
	}
	return nil
}
