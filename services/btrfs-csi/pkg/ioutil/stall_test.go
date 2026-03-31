package ioutil

import (
	"bytes"
	"context"
	"io"
	"strings"
	"testing"
	"time"
)

func TestStallReader_NormalRead(t *testing.T) {
	data := "hello world, this is a normal read test"
	ctx, cancel := context.WithCancelCause(context.Background())
	defer cancel(nil)

	sr := NewStallReader(strings.NewReader(data), ctx, cancel, 1*time.Second)
	defer sr.Close()

	got, err := io.ReadAll(sr)
	if err != nil {
		t.Fatalf("ReadAll error: %v", err)
	}
	if string(got) != data {
		t.Errorf("got %q, want %q", string(got), data)
	}
	if ctx.Err() != nil {
		t.Errorf("context cancelled unexpectedly: %v (cause: %v)", ctx.Err(), context.Cause(ctx))
	}
}

func TestStallReader_StallDetected(t *testing.T) {
	// Writer sends some bytes then stops — simulates a stalled btrfs send.
	pr, pw := io.Pipe()
	go func() {
		pw.Write([]byte("initial bytes"))
		// Block forever — stall detection should close the pipe.
		select {}
	}()

	ctx, cancel := context.WithCancelCause(context.Background())
	sr := NewStallReader(pr, ctx, cancel, 100*time.Millisecond)
	defer sr.Close()

	buf := make([]byte, 64)
	n, err := sr.Read(buf)
	if err != nil || n == 0 {
		t.Fatalf("initial Read: n=%d, err=%v", n, err)
	}

	// The reader blocks — stall timer should fire and close the pipe.
	_, readErr := sr.Read(buf)
	if readErr == nil {
		t.Fatal("expected error from stalled read")
	}

	// Context should be cancelled with stall cause.
	cause := context.Cause(ctx)
	if cause == nil || !strings.Contains(cause.Error(), "stall") {
		t.Errorf("expected stall cause, got: %v", cause)
	}
}

func TestStallReader_SlowButProgressing(t *testing.T) {
	pr, pw := io.Pipe()
	go func() {
		for i := 0; i < 10; i++ {
			time.Sleep(50 * time.Millisecond)
			pw.Write([]byte{byte('a' + i)})
		}
		pw.Close()
	}()

	ctx, cancel := context.WithCancelCause(context.Background())
	defer cancel(nil)

	sr := NewStallReader(pr, ctx, cancel, 200*time.Millisecond)
	defer sr.Close()

	got, err := io.ReadAll(sr)
	if err != nil {
		t.Fatalf("ReadAll error: %v", err)
	}
	if len(got) != 10 {
		t.Errorf("got %d bytes, want 10", len(got))
	}
	if ctx.Err() != nil {
		t.Errorf("context cancelled for slow-but-progressing reader: %v", context.Cause(ctx))
	}
}

func TestStallReader_CloseStopsTimer(t *testing.T) {
	ctx, cancel := context.WithCancelCause(context.Background())
	defer cancel(nil)

	sr := NewStallReader(strings.NewReader("data"), ctx, cancel, 100*time.Millisecond)
	io.ReadAll(sr)
	sr.Close()

	time.Sleep(200 * time.Millisecond)

	if ctx.Err() != nil {
		t.Errorf("context cancelled after Close: %v", context.Cause(ctx))
	}
}

func TestStallReader_ZeroBytesRead(t *testing.T) {
	callCount := 0
	zeroReader := readerFunc(func(p []byte) (int, error) {
		callCount++
		if callCount <= 5 {
			return 0, nil
		}
		return 0, io.EOF
	})

	ctx, cancel := context.WithCancelCause(context.Background())
	sr := NewStallReader(zeroReader, ctx, cancel, 100*time.Millisecond)
	defer sr.Close()

	io.ReadAll(sr)
	time.Sleep(200 * time.Millisecond)

	if ctx.Err() == nil {
		t.Error("expected stall detection for zero-byte reads")
	}
}

func TestStallReader_LargeData(t *testing.T) {
	data := bytes.Repeat([]byte("x"), 1<<20)
	ctx, cancel := context.WithCancelCause(context.Background())
	defer cancel(nil)

	sr := NewStallReader(bytes.NewReader(data), ctx, cancel, 1*time.Second)
	defer sr.Close()

	got, err := io.ReadAll(sr)
	if err != nil {
		t.Fatalf("ReadAll error: %v", err)
	}
	if len(got) != len(data) {
		t.Errorf("got %d bytes, want %d", len(got), len(data))
	}
	if ctx.Err() != nil {
		t.Errorf("context cancelled for large read: %v", context.Cause(ctx))
	}
}

// readerFunc adapts a function to the io.Reader interface.
type readerFunc func([]byte) (int, error)

func (f readerFunc) Read(p []byte) (int, error) { return f(p) }
