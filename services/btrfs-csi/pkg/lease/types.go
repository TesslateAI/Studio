// Package lease defines shared types for the volume lease system used by both
// the sync daemon and the volume hub. This avoids import cycles between the
// sync and volumehub packages.
package lease

import "time"

// BatchReq is a single entry in a batch lease acquisition request.
type BatchReq struct {
	VolumeID string
	Holder   string
	TTL      time.Duration
}

// BatchResult is the result for a single volume in a batch lease request.
type BatchResult struct {
	VolumeID      string
	Acquired      bool
	CurrentHolder string // non-empty when Acquired==false
}
