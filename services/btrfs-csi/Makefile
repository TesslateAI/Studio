# Build orchestration for the btrfs-csi service and its sibling
# sidecars (write-tracker for Tier 1 ephemeral compute pods).
#
# This Makefile only wraps the standard ``go build`` and ``docker build``
# invocations — there is no fancy templating. CI consumes the same
# targets so local + CI builds stay 1:1.

REGISTRY ?= opensail
TAG ?= latest

.PHONY: all
all: csi-driver write-tracker

# ---------------------------------------------------------------------
# csi-driver — the main btrfs CSI plugin (existing image).
# ---------------------------------------------------------------------
.PHONY: csi-driver
csi-driver:
	docker build -t $(REGISTRY)/tesslate-btrfs-csi:$(TAG) .

# ---------------------------------------------------------------------
# write-tracker — Tier 1 sidecar that reports filesystem writes
# outside /tmp + /automations via inotify. Lives at
# cmd/write-tracker/ with its own Dockerfile so the scratch image
# stays minimal.
# ---------------------------------------------------------------------
.PHONY: write-tracker
write-tracker:
	docker build \
		-f cmd/write-tracker/Dockerfile \
		-t $(REGISTRY)/opensail-write-tracker:$(TAG) \
		.

# ---------------------------------------------------------------------
# Local Go test pass for the standalone cmd packages. The driver +
# pkg/* tests live under integration/ and run inside a privileged
# container — see integration/Makefile.
# ---------------------------------------------------------------------
.PHONY: test
test:
	go test ./cmd/... ./pkg/...

.PHONY: clean
clean:
	docker rmi $(REGISTRY)/tesslate-btrfs-csi:$(TAG) 2>/dev/null || true
	docker rmi $(REGISTRY)/opensail-write-tracker:$(TAG) 2>/dev/null || true
