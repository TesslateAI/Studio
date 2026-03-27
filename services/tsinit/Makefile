VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")
LDFLAGS = -s -w -X main.version=$(VERSION)
BINARY  = tsinit
IMAGE   = tsinit-test

.PHONY: build build-linux test test-integration clean

build:
	go build -ldflags "$(LDFLAGS)" -o $(BINARY) .

build-linux:
	CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -ldflags "$(LDFLAGS)" -o $(BINARY)-linux-amd64 .
	CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -ldflags "$(LDFLAGS)" -o $(BINARY)-linux-arm64 .

test:
	go test ./...

# Build the integration test image and run it. tsinit boots as PID 1
# and launches the test binary as a managed process inside the container.
test-integration:
	docker build -t $(IMAGE) -f integration/Dockerfile .
	docker run --rm $(IMAGE)

clean:
	rm -f $(BINARY) $(BINARY)-linux-*
