// Package cache provides a lightweight in-memory TTL cache backed by
// sync.Map. Used to cache session existence checks so the pipeline trigger
// path avoids a PostgreSQL round-trip on every request.
package cache

import (
	"sync"
	"time"
)

type entry struct {
	value     any
	expiresAt time.Time
}

// TTLCache is a goroutine-safe key/value cache with per-entry expiration.
// Zero value is NOT usable; call New().
type TTLCache struct {
	m   sync.Map
	ttl time.Duration
}

// New returns a cache where entries expire after ttl. A background goroutine
// evicts expired entries every ttl/2 to bound memory.
func New(ttl time.Duration) *TTLCache {
	c := &TTLCache{ttl: ttl}
	go c.reap(ttl / 2)
	return c
}

// Get retrieves a value. Returns (value, true) on hit, (nil, false) on miss
// or expiry.
func (c *TTLCache) Get(key string) (any, bool) {
	raw, ok := c.m.Load(key)
	if !ok {
		return nil, false
	}
	e := raw.(entry)
	if time.Now().After(e.expiresAt) {
		c.m.Delete(key)
		return nil, false
	}
	return e.value, true
}

// Set stores a value with the cache's default TTL.
func (c *TTLCache) Set(key string, value any) {
	c.m.Store(key, entry{value: value, expiresAt: time.Now().Add(c.ttl)})
}

// reap periodically evicts expired entries.
func (c *TTLCache) reap(interval time.Duration) {
	tick := time.NewTicker(interval)
	defer tick.Stop()
	for range tick.C {
		now := time.Now()
		c.m.Range(func(key, raw any) bool {
			if e := raw.(entry); now.After(e.expiresAt) {
				c.m.Delete(key)
			}
			return true
		})
	}
}
