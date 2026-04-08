// Package kafka provides Kafka producer and consumer wrappers for the
// MedScribe API gateway.
package kafka

import (
	"context"
	"fmt"
	"strings"
	"sync"

	ckafka "github.com/confluentinc/confluent-kafka-go/v2/kafka"
	"github.com/medscribe/services/api/config"
	"go.uber.org/zap"
)

// MessageHandler is the callback signature for processing consumed messages.
// Return nil to commit the offset; return an error to skip (logged, not retried).
type MessageHandler func(ctx context.Context, key, value []byte) error

// Consumer wraps a confluent-kafka-go consumer for a single topic with
// at-least-once delivery semantics and graceful shutdown. When Workers > 1,
// messages are dispatched to a goroutine pool for concurrent processing.
type Consumer struct {
	c       *ckafka.Consumer
	topic   string
	handler MessageHandler
	log     *zap.Logger
	wg      sync.WaitGroup
	cancel  context.CancelFunc
	workers int // concurrent handler goroutines (default 1 = serial)
}

// NewConsumer creates a Kafka consumer subscribed to the given topic.
// The consumer group is derived from the topic name unless overridden via
// KAFKA_CONSUMER_GROUP env var.
func NewConsumer(
	cfg config.KafkaConfig,
	topic string,
	groupID string,
	handler MessageHandler,
	log *zap.Logger,
) (*Consumer, error) {
	c, err := ckafka.NewConsumer(&ckafka.ConfigMap{
		"bootstrap.servers":  strings.Join(cfg.Brokers, ","),
		"group.id":           groupID,
		"auto.offset.reset":  "earliest",
		"enable.auto.commit": false,
		// Session timeout — broker marks consumer dead if no heartbeat within
		// this window. 30s balances fast rebalance vs false positives.
		"session.timeout.ms": 30000,
		"max.poll.interval.ms": 300000, // 5 min for long pipeline runs
	})
	if err != nil {
		return nil, fmt.Errorf("kafka consumer: create: %w", err)
	}

	if err = c.Subscribe(topic, nil); err != nil {
		c.Close()
		return nil, fmt.Errorf("kafka consumer: subscribe to %s: %w", topic, err)
	}

	workers := 1
	if cfg.Workers > 0 {
		workers = cfg.Workers
	}

	return &Consumer{
		c:       c,
		topic:   topic,
		handler: handler,
		log:     log,
		workers: workers,
	}, nil
}

// Start begins consuming messages in a background goroutine. Call Close to
// stop the consumer gracefully.
func (co *Consumer) Start(ctx context.Context) {
	ctx, co.cancel = context.WithCancel(ctx)
	co.wg.Add(1)
	go co.run(ctx)
	co.log.Info("kafka consumer started",
		zap.String("topic", co.topic),
	)
}

func (co *Consumer) run(ctx context.Context) {
	defer co.wg.Done()

	// Semaphore for bounding concurrent handler goroutines.
	sem := make(chan struct{}, co.workers)
	var commitMu sync.Mutex

	for {
		select {
		case <-ctx.Done():
			// Drain in-flight workers before returning.
			for i := 0; i < co.workers; i++ {
				sem <- struct{}{}
			}
			return
		default:
		}

		ev := co.c.Poll(500) // 500ms poll timeout
		if ev == nil {
			continue
		}

		switch e := ev.(type) {
		case *ckafka.Message:
			if co.workers <= 1 {
				// Serial path — original behaviour.
				if err := co.handler(ctx, e.Key, e.Value); err != nil {
					co.log.Error("kafka consumer: handler error",
						zap.String("topic", co.topic),
						zap.String("key", string(e.Key)),
						zap.Error(err),
					)
				}
				if _, err := co.c.CommitMessage(e); err != nil {
					co.log.Warn("kafka consumer: commit offset failed",
						zap.Error(err),
					)
				}
			} else {
				// Concurrent path — dispatch to worker pool.
				sem <- struct{}{} // acquire slot (blocks if pool full)
				msg := e
				go func() {
					defer func() { <-sem }() // release slot
					if err := co.handler(ctx, msg.Key, msg.Value); err != nil {
						co.log.Error("kafka consumer: handler error",
							zap.String("topic", co.topic),
							zap.String("key", string(msg.Key)),
							zap.Error(err),
						)
					}
					commitMu.Lock()
					if _, err := co.c.CommitMessage(msg); err != nil {
						co.log.Warn("kafka consumer: commit offset failed",
							zap.Error(err),
						)
					}
					commitMu.Unlock()
				}()
			}

		case ckafka.Error:
			// Broker-level errors are informational in librdkafka; the client
			// reconnects automatically. Log and continue.
			co.log.Warn("kafka consumer: broker error",
				zap.String("topic", co.topic),
				zap.Error(e),
			)
		}
	}
}

// Close stops consuming and waits for the background goroutine to exit.
func (co *Consumer) Close() {
	if co.cancel != nil {
		co.cancel()
	}
	co.wg.Wait()
	co.c.Close()
	co.log.Info("kafka consumer stopped", zap.String("topic", co.topic))
}
