// Package kafka provides a thin Kafka producer for publishing pipeline trigger
// messages and transcript ingest events.
package kafka

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/confluentinc/confluent-kafka-go/v2/kafka"
	"github.com/medscribe/services/api/config"
)

// Producer wraps a confluent-kafka-go producer with typed publish helpers.
// It runs a background goroutine to drain the delivery-report channel so
// async produces don't block.
type Producer struct {
	p       *kafka.Producer
	timeout time.Duration
}

// New creates a Kafka producer from config. Verifies broker connectivity via
// a metadata fetch before returning.
func New(cfg config.KafkaConfig) (*Producer, error) {
	p, err := kafka.NewProducer(&kafka.ConfigMap{
		"bootstrap.servers": strings.Join(cfg.Brokers, ","),
		"socket.timeout.ms":  5000,
		"message.timeout.ms": int(cfg.ProducerTimeout.Milliseconds()),

		// Leader-only ack: single-broker Docker setup gains nothing from
		// acks=all since there are no replicas. Even in production with a
		// multi-broker cluster, leader ack is sufficient for a fire-and-poll
		// pipeline trigger where the client polls Redis for status.
		"acks":    "1",
		"retries": 3,
		"retry.backoff.ms": 100,

		// Micro-batching: buffer up to 10ms before flushing to Kafka. This
		// coalesces concurrent triggers into fewer broker round-trips.
		// At 500 QPS the producer accumulates ~5 messages per 10ms window,
		// which is enough to amortize the syscall overhead.
		"queue.buffering.max.messages": 100000,
		"queue.buffering.max.ms":       10,
		"batch.size":                   65536, // 64 KB byte limit per batch

		"compression.type": "snappy",
	})
	if err != nil {
		return nil, fmt.Errorf("kafka: create producer: %w", err)
	}

	// Verify broker reachability.
	if _, err = p.GetMetadata(nil, true, 5000); err != nil {
		p.Close()
		return nil, fmt.Errorf("kafka: broker unreachable: %w", err)
	}

	pr := &Producer{p: p, timeout: cfg.ProducerTimeout}

	// Background goroutine drains the delivery report channel so async
	// produces never block waiting for the caller to read events.
	go pr.drainEvents()

	return pr, nil
}

// drainEvents reads the producer Events channel forever, logging failures.
// Exits when the channel is closed (on producer.Close()).
func (pr *Producer) drainEvents() {
	for ev := range pr.p.Events() {
		switch e := ev.(type) {
		case *kafka.Message:
			if e.TopicPartition.Error != nil {
				fmt.Printf("kafka: async delivery failed: topic=%s err=%v\n",
					*e.TopicPartition.Topic, e.TopicPartition.Error)
			}
		}
	}
}

// PublishJSON serializes v as JSON and enqueues it to the Kafka producer's
// internal buffer. It returns as soon as the message is accepted by the
// local buffer -- it does NOT block on broker acknowledgment. Delivery
// errors are handled asynchronously by drainEvents().
//
// This is safe because the pipeline trigger is fire-and-poll: the client
// receives 202 Accepted immediately and polls Redis for status. If delivery
// fails the pipeline simply never starts and the status stays "pending"
// until it times out, which the client already handles.
func (pr *Producer) PublishJSON(ctx context.Context, topic, key string, v any) error {
	payload, err := json.Marshal(v)
	if err != nil {
		return fmt.Errorf("kafka: marshal payload: %w", err)
	}

	// nil deliveryCh = async produce. Delivery reports go to pr.p.Events()
	// and are drained by the background goroutine.
	if err = pr.p.Produce(&kafka.Message{
		TopicPartition: kafka.TopicPartition{Topic: &topic, Partition: kafka.PartitionAny},
		Key:            []byte(key),
		Value:          payload,
	}, nil); err != nil {
		return fmt.Errorf("kafka: enqueue message: %w", err)
	}

	return nil
}

// Close flushes pending messages and releases resources.
func (pr *Producer) Close() {
	pr.p.Flush(int(pr.timeout.Milliseconds()))
	pr.p.Close()
}
