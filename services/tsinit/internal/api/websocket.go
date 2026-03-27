package api

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"sync"
	"sync/atomic"

	"github.com/gorilla/websocket"
)

// wsCounter ensures unique WebSocket subscription IDs even on rapid reconnect.
var wsCounter atomic.Uint64

// wsUpgrader is the default WebSocket upgrader. We accept all origins because
// this runs inside a container — access control is handled at the ingress layer.
var wsUpgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool { return true },
}

// wsControlMessage is a JSON control message sent as a WebSocket text frame.
type wsControlMessage struct {
	Type string `json:"type"`
	Cols int    `json:"cols,omitempty"`
	Rows int    `json:"rows,omitempty"`
}

// handleProcessStream handles GET /v1/processes/{name}/stream.
// It upgrades the connection to WebSocket and provides bidirectional PTY
// streaming:
//   - Binary frames from client -> process PTY stdin
//   - Text frames from client -> control messages (e.g. resize)
//   - Process output -> binary frames to client
func (s *Server) handleProcessStream(w http.ResponseWriter, r *http.Request) {
	name := r.PathValue("name")
	proc, ok := s.manager.Get(name)
	if !ok {
		writeError(w, http.StatusNotFound, "process not found: "+name)
		return
	}

	conn, err := wsUpgrader.Upgrade(w, r, nil)
	if err != nil {
		slog.Error("websocket upgrade failed", "name", name, "error", err)
		return
	}

	// Generate a unique subscription ID for this stream.
	subID := fmt.Sprintf("ws-%s-%d", name, wsCounter.Add(1))
	outputCh := proc.Subscribe(subID)

	// closeOnce ensures we only clean up once regardless of which goroutine
	// exits first.
	var closeOnce sync.Once
	cleanup := func() {
		proc.Unsubscribe(subID)
		conn.Close()
	}

	slog.Debug("websocket stream opened", "name", name, "sub_id", subID)

	// Goroutine 1: Read from process output subscription -> write to WebSocket.
	go func() {
		defer closeOnce.Do(cleanup)
		for data := range outputCh {
			if err := conn.WriteMessage(websocket.BinaryMessage, data); err != nil {
				slog.Debug("websocket write error", "name", name, "error", err)
				return
			}
		}
	}()

	// Goroutine 2 (runs on this goroutine): Read from WebSocket -> write to process PTY.
	defer closeOnce.Do(cleanup)
	for {
		msgType, data, err := conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err,
				websocket.CloseNormalClosure,
				websocket.CloseGoingAway,
			) {
				slog.Debug("websocket read error", "name", name, "error", err)
			}
			return
		}

		switch msgType {
		case websocket.BinaryMessage:
			// Raw PTY input.
			if _, err := proc.WriteInput(data); err != nil {
				slog.Debug("pty write error", "name", name, "error", err)
				return
			}

		case websocket.TextMessage:
			// Control message (JSON).
			var ctrl wsControlMessage
			if err := json.Unmarshal(data, &ctrl); err != nil {
				slog.Debug("invalid control message", "name", name, "error", err)
				continue
			}
			switch ctrl.Type {
			case "resize":
				if ctrl.Cols > 0 && ctrl.Rows > 0 {
					if err := proc.Resize(ctrl.Cols, ctrl.Rows); err != nil {
						slog.Debug("resize failed", "name", name, "error", err)
					}
				}
			default:
				slog.Debug("unknown control message type", "name", name, "type", ctrl.Type)
			}
		}
	}
}
