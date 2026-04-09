package ioutil

import (
	"context"
	"errors"
	"fmt"
	"io"
	"sync"
	"time"
)

// StallTimeout is the duration of zero I/O progress before an operation is
// considered stuck. 30 seconds is conservative — even on a slow S3 connection,
// partial reads should happen more frequently. A real stall (network partition,
// dead rclone) produces zero bytes immediately.
const StallTimeout = 30 * time.Second

// ErrStall is the sentinel error used when a stall is detected. Callers can
// check for it with errors.Is(err, ioutil.ErrStall).
var ErrStall = errors.New("I/O stall")

// StallReader wraps an io.Reader and cancels a context if no bytes are read
// within the stall timeout. Every successful Read (n > 0) resets the timer.
// This distinguishes "stuck" (zero bytes for 30s) from "slow but progressing"
// (large upload at 1MB/s). Implements io.ReadCloser.
//
// When the stall timer fires, it cancels the context AND closes the underlying
// reader (if it implements io.Closer). This unblocks any Read() call that's
// stuck waiting on the underlying reader (e.g., io.Pipe, btrfs send stdout).
type StallReader struct {
	r         io.Reader
	cancel    context.CancelCauseFunc
	timeout   time.Duration
	timer     *time.Timer
	ctx       context.Context
	closeOnce sync.Once
	closeErr  error
}

// NewStallReader wraps r with stall detection. If no bytes are read for
// timeout duration, cancel is called with a descriptive error and the
// underlying reader is closed to unblock any stuck Read. The caller
// must call Close() when done to stop the timer.
func NewStallReader(r io.Reader, ctx context.Context, cancel context.CancelCauseFunc, timeout time.Duration) *StallReader {
	sr := &StallReader{
		r:       r,
		cancel:  cancel,
		timeout: timeout,
		ctx:     ctx,
	}
	sr.timer = time.AfterFunc(timeout, func() {
		cancel(fmt.Errorf("%w: no bytes read for %v", ErrStall, timeout))
		// Close the underlying reader to unblock any stuck Read().
		// Uses closeOnce to prevent double-close race with Close().
		sr.closeOnce.Do(func() {
			if c, ok := r.(io.Closer); ok {
				sr.closeErr = c.Close()
			}
		})
	})
	return sr
}

// Read delegates to the underlying reader. If any bytes are read (n > 0),
// the stall timer is reset. Zero-byte reads do not reset the timer.
// If the context was cancelled (by stall timer or parent), returns the
// context error.
func (sr *StallReader) Read(p []byte) (int, error) {
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
func (sr *StallReader) Close() error {
	sr.timer.Stop()
	sr.closeOnce.Do(func() {
		if c, ok := sr.r.(io.Closer); ok {
			sr.closeErr = c.Close()
		}
	})
	return sr.closeErr
}
