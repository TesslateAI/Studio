# Integration test image: tsinit as PID 1 in a real container.
# Build: docker build -t tsinit-test -f integration/Dockerfile .
# Run:   docker run --rm tsinit-test
FROM golang:1.22-alpine AS builder

RUN apk add --no-cache git

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .

# Build the binary (static, no CGO)
RUN CGO_ENABLED=0 go build -ldflags "-s -w -X main.version=integration-test" \
    -o /tsinit .

# Build the test runner (static binary that runs the integration tests)
RUN CGO_ENABLED=0 go test -c -o /integration-tests ./integration/ \
    -tags integration

# --- Runtime image ---
FROM alpine:3.20

# Install tools the test processes need
RUN apk add --no-cache bash curl nodejs npm python3

# Run as non-root (matches production devserver containers)
RUN adduser -D -u 1000 testuser
COPY --from=builder /tsinit /usr/local/bin/tsinit
COPY --from=builder /integration-tests /usr/local/bin/integration-tests
RUN mkdir -p /var/run && chown testuser:testuser /var/run

USER testuser

# tsinit as PID 1, starts the test runner as a managed process
# The test runner talks to tsinit via the API to exercise all features.
ENTRYPOINT ["tsinit", "serve", \
    "--tcp-addr", ":9111", \
    "--sock-path", "/var/run/tsinit.sock", \
    "--process", "tests=integration-tests -test.v -test.timeout 120s"]
