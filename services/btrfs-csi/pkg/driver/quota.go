package driver

import (
	"strconv"
	"strings"
)

// ParseQuota converts a human-readable size string (e.g., "5Gi", "500Mi") to bytes.
// Returns 0 for empty or unparseable input.
func ParseQuota(s string) int64 {
	s = strings.TrimSpace(s)
	if s == "" {
		return 0
	}
	multipliers := map[string]int64{
		"Ki": 1024,
		"Mi": 1024 * 1024,
		"Gi": 1024 * 1024 * 1024,
		"Ti": 1024 * 1024 * 1024 * 1024,
	}
	for suffix, mul := range multipliers {
		if numStr, ok := strings.CutSuffix(s, suffix); ok {
			val, err := strconv.ParseInt(numStr, 10, 64)
			if err != nil {
				return 0
			}
			return val * mul
		}
	}
	val, err := strconv.ParseInt(s, 10, 64)
	if err != nil {
		return 0
	}
	return val
}
