# Tier 1 ephemeral compute sidecar — write-tracker.
#
# Multi-stage build: a Go static binary linked against musl/sysroot-free
# stdlib, then dropped into a distroless/static base for the runtime
# image. Final image is ~6 MiB — small enough that the sidecar adds
# negligible cold-start overhead to a Tier 1 pod.
FROM golang:1.25-alpine AS builder
ENV GOTOOLCHAIN=auto

WORKDIR /build

# Cache module downloads when only Go sources change.
COPY go.mod go.sum ./
RUN go mod download

COPY . .

# Static build: the distroless/static base has no libc, so CGO must
# stay off and the binary must be fully self-contained.
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build \
    -ldflags="-s -w" \
    -o /opensail-write-tracker \
    ./cmd/write-tracker

# Distroless static base: no shell, no package manager, no apk.
# Runs as a non-root user via the K8s pod securityContext.
FROM gcr.io/distroless/static:nonroot

COPY --from=builder /opensail-write-tracker /usr/local/bin/opensail-write-tracker

# The sidecar runs entirely from inotify; no args, no flags.
USER 1000:1000
ENTRYPOINT ["/usr/local/bin/opensail-write-tracker"]
