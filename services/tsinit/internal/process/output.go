package process

import (
	"bytes"
	"sync"
)

// RingBuffer is a thread-safe circular buffer that stores process output by line.
// It keeps at most `capacity` complete lines, discarding the oldest when full.
type RingBuffer struct {
	mu       sync.Mutex
	lines    [][]byte
	head     int // index of the oldest line
	count    int // number of lines stored
	capacity int
	partial  []byte // incomplete line accumulator (no trailing newline yet)
}

// NewRingBuffer creates a ring buffer that holds up to capacity lines.
func NewRingBuffer(capacity int) *RingBuffer {
	if capacity <= 0 {
		capacity = 1000
	}
	return &RingBuffer{
		lines:    make([][]byte, capacity),
		capacity: capacity,
	}
}

// Write splits incoming data into lines and appends complete lines to the
// ring buffer. Partial lines (data that does not end with \n) are accumulated
// internally and flushed when the next newline arrives.
func (rb *RingBuffer) Write(data []byte) {
	rb.mu.Lock()
	defer rb.mu.Unlock()

	// Prepend any buffered partial data.
	if len(rb.partial) > 0 {
		data = append(rb.partial, data...)
		rb.partial = nil
	}

	for len(data) > 0 {
		idx := bytes.IndexByte(data, '\n')
		if idx == -1 {
			// No newline found — buffer the remainder as a partial line.
			rb.partial = make([]byte, len(data))
			copy(rb.partial, data)
			return
		}

		// Extract the complete line (excluding the newline character).
		line := make([]byte, idx)
		copy(line, data[:idx])
		rb.appendLine(line)

		data = data[idx+1:]
	}
}

// appendLine adds a single complete line to the ring buffer. Caller must hold mu.
func (rb *RingBuffer) appendLine(line []byte) {
	if rb.count < rb.capacity {
		rb.lines[(rb.head+rb.count)%rb.capacity] = line
		rb.count++
	} else {
		// Overwrite the oldest entry.
		rb.lines[rb.head] = line
		rb.head = (rb.head + 1) % rb.capacity
	}
}

// Lines returns the last n lines stored in the buffer, ordered oldest to newest.
// If n <= 0 or n > stored count, all stored lines are returned.
func (rb *RingBuffer) Lines(n int) []string {
	rb.mu.Lock()
	defer rb.mu.Unlock()

	total := rb.count
	if n <= 0 || n > total {
		n = total
	}

	result := make([]string, n)
	// Start from (count - n) offset from head.
	start := (rb.head + rb.count - n) % rb.capacity
	for i := 0; i < n; i++ {
		idx := (start + i) % rb.capacity
		result[i] = string(rb.lines[idx])
	}
	return result
}

// Len returns the number of complete lines currently stored.
func (rb *RingBuffer) Len() int {
	rb.mu.Lock()
	defer rb.mu.Unlock()
	return rb.count
}
