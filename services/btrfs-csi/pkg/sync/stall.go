package sync

import (
	"context"
	"fmt"
	"io"
	"time"
)

// syncStallTimeout is the duration of zero I/O progress before a sync is
// considered stuck. 30 seconds is conservative — even on a slow S3 connection,
// partial reads should happen more frequently. A real stall (network partition,
// dead rclone) produces zero bytes immediately.
const syncStallTimeout = 30 * time.Second

// stallReader wraps an io.Reader and cancels a context if no bytes are read
// within the stall timeout. Every successful Read (n > 0) resets the timer.
// This distinguishes "stuck" (zero bytes for 30s) from "slow but progressing"
// (large upload at 1MB/s). Implements io.ReadCloser.
//
// When the stall timer fires, it cancels the context AND closes the underlying
// reader (if it implements io.Closer). This unblocks any Read() call that's
// stuck waiting on the underlying reader (e.g., io.Pipe, btrfs send stdout).
type stallReader struct {
	r       io.Reader
	cancel  context.CancelCauseFunc
	timeout time.Duration
	timer   *time.Timer
	ctx     context.Context
}

// newStallReader wraps r with stall detection. If no bytes are read for
// timeout duration, cancel is called with a descriptive error and the
// underlying reader is closed to unblock any stuck Read. The caller
// must call Close() when done to stop the timer.
func newStallReader(r io.Reader, ctx context.Context, cancel context.CancelCauseFunc, timeout time.Duration) *stallReader {
	sr := &stallReader{
		r:       r,
		cancel:  cancel,
		timeout: timeout,
		ctx:     ctx,
	}
	sr.timer = time.AfterFunc(timeout, func() {
		cancel(fmt.Errorf("I/O stall: no bytes read for %v", timeout))
		// Close the underlying reader to unblock any stuck Read().
		if c, ok := r.(io.Closer); ok {
			c.Close()
		}
	})
	return sr
}

// Read delegates to the underlying reader. If any bytes are read (n > 0),
// the stall timer is reset. Zero-byte reads do not reset the timer.
// If the context was cancelled (by stall timer or parent), returns the
// context error.
func (sr *stallReader) Read(p []byte) (int, error) {
	n, err := sr.r.Read(p)
	if n > 0 {
		sr.timer.Reset(sr.timeout)
	}
	// If the read failed and our context is done, surface the context error
	// so callers see the stall cause instead of a generic pipe/EOF error.
	if err != nil && sr.ctx.Err() != nil {
		return n, sr.ctx.Err()
	}
	return n, err
}

// Close stops the stall timer and closes the underlying reader if it
// implements io.Closer. Must be called to prevent a stale timer from
// firing after a successful operation.
func (sr *stallReader) Close() error {
	sr.timer.Stop()
	if c, ok := sr.r.(io.Closer); ok {
		return c.Close()
	}
	return nil
}
