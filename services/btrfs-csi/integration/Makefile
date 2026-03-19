.PHONY: test load-test clean

# Build and run integration tests inside a Docker container with a real btrfs filesystem.
# Requires: Docker with --privileged (for loopback mount)
test:
	docker build -f Dockerfile.test -t tesslate-btrfs-csi-test ..
	docker run --rm --privileged tesslate-btrfs-csi-test

# Load tests: larger pool, longer timeout, separate build tags.
load-test:
	docker build -f Dockerfile.test -t tesslate-btrfs-csi-test ..
	docker run --rm --privileged -e BTRFS_POOL_SIZE=5G -e EXTRA_TEST_TAGS=load -e TEST_TIMEOUT=600s tesslate-btrfs-csi-test

clean:
	docker rmi tesslate-btrfs-csi-test 2>/dev/null || true
