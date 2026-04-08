# ─── build stage ──────────────────────────────────────────────────────────────
FROM golang:1.26-alpine AS builder

# Install build deps for confluent-kafka-go (requires librdkafka headers).
RUN apk add --no-cache gcc musl-dev bash

WORKDIR /build

# Cache dependencies before copying source.
COPY go.mod go.sum ./
RUN go mod download

COPY . .

RUN CGO_ENABLED=1 GOOS=linux go build \
    -tags musl \
    -ldflags="-s -w" \
    -o /bin/medscribe-api \
    ./cmd/app

# ─── runtime stage ────────────────────────────────────────────────────────────
FROM alpine:3.21

# Non-root user for least-privilege execution.
RUN addgroup -S medscribe && adduser -S medscribe -G medscribe

COPY --from=builder /bin/medscribe-api /bin/medscribe-api

USER medscribe

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://localhost:8080/health || exit 1

ENTRYPOINT ["/bin/medscribe-api"]
