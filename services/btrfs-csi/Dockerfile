FROM golang:1.24-alpine AS builder
ENV GOTOOLCHAIN=auto

RUN apk add --no-cache git

WORKDIR /build

COPY go.mod go.sum ./
RUN go mod download

COPY . .

RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build \
    -ldflags="-s -w -X main.version=$(git describe --tags --always --dirty 2>/dev/null || echo dev)" \
    -o /tesslate-btrfs-csi \
    ./cmd/driver

FROM alpine:3.20

RUN apk add --no-cache btrfs-progs e2fsprogs util-linux zstd rclone

COPY --from=builder /tesslate-btrfs-csi /usr/local/bin/tesslate-btrfs-csi

# Default to non-root; K8s DaemonSet overrides via securityContext.runAsUser: 0
# for the node plugin which requires root for mount/btrfs operations.
RUN addgroup -S csi && adduser -S csi -G csi
USER csi

ENTRYPOINT ["/usr/local/bin/tesslate-btrfs-csi"]
