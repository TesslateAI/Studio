package volumehub

import (
	"bufio"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"sync"
	"time"

	"k8s.io/klog/v2"
)

// NodeResolver maintains a mapping from K8s node names to CSI node pod IPs.
// It discovers nodes via the K8s Endpoints API using the in-cluster service
// account token — no client-go dependency, just net/http.
//
// StartWatch establishes a long-lived HTTP watch connection that delivers
// endpoint changes in ~1s (vs the old 30s polling approach).
type NodeResolver struct {
	mu         sync.RWMutex
	nodeToAddr map[string]string // K8s node name → podIP:port
	svcName    string            // headless service name (e.g. "tesslate-btrfs-csi-node-svc")
	namespace           string            // namespace of the service (e.g. "kube-system")
	port                int               // NodeOps gRPC port on the CSI node pods
	apiHost             string            // K8s API server host (from KUBERNETES_SERVICE_HOST)
	token               string            // service account token
	httpClient          *http.Client      // 10s timeout, for list requests
	watchClient         *http.Client      // no timeout, for long-lived watch connections
}

// NewNodeResolver creates a NodeResolver that discovers CSI nodes via the
// K8s Endpoints API. Uses in-cluster service account credentials.
func NewNodeResolver(svcName, namespace string, port int) (*NodeResolver, error) {
	apiHost := os.Getenv("KUBERNETES_SERVICE_HOST")
	apiPort := os.Getenv("KUBERNETES_SERVICE_PORT")
	if apiHost == "" || apiPort == "" {
		return nil, fmt.Errorf("not running in-cluster: KUBERNETES_SERVICE_HOST/PORT not set")
	}

	tokenBytes, err := os.ReadFile("/var/run/secrets/kubernetes.io/serviceaccount/token")
	if err != nil {
		return nil, fmt.Errorf("read service account token: %w", err)
	}

	// Use the cluster CA if available, otherwise skip verification for
	// in-cluster communication (API server cert is self-signed).
	tlsCfg := &tls.Config{MinVersion: tls.VersionTLS12}
	caPath := "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
	if _, statErr := os.Stat(caPath); statErr == nil {
		caCert, readErr := os.ReadFile(caPath)
		if readErr == nil {
			pool := x509.NewCertPool()
			pool.AppendCertsFromPEM(caCert)
			tlsCfg.RootCAs = pool
		}
	}

	transport := &http.Transport{TLSClientConfig: tlsCfg}

	return &NodeResolver{
		nodeToAddr: make(map[string]string),
		svcName:    svcName,
		namespace:  namespace,
		port:       port,
		apiHost:    fmt.Sprintf("https://%s:%s", apiHost, apiPort),
		token:      string(tokenBytes),
		httpClient: &http.Client{
			Timeout:   10 * time.Second,
			Transport: transport,
		},
		watchClient: &http.Client{
			Timeout:   0, // no timeout for long-lived watch
			Transport: transport,
		},
	}, nil
}

// newTestNodeResolver creates a NodeResolver for unit tests, pointing at a
// custom API host with no TLS or service account token.
func newTestNodeResolver(apiHost, svcName, namespace string, port int) *NodeResolver {
	return &NodeResolver{
		nodeToAddr:  make(map[string]string),
		svcName:     svcName,
		namespace:   namespace,
		port:        port,
		apiHost:     apiHost,
		token:       "test-token",
		httpClient:  &http.Client{Timeout: 5 * time.Second},
		watchClient: &http.Client{Timeout: 0},
	}
}

// Refresh queries the K8s Endpoints API (list) and updates the node→addr map.
// Returns the resourceVersion from the response, used to start a watch.
func (r *NodeResolver) Refresh(ctx context.Context) (string, error) {
	url := fmt.Sprintf("%s/api/v1/namespaces/%s/endpoints/%s", r.apiHost, r.namespace, r.svcName)

	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return "", fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+r.token)
	req.Header.Set("Accept", "application/json")

	resp, err := r.httpClient.Do(req)
	if err != nil {
		return "", fmt.Errorf("endpoints API call: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
		return "", fmt.Errorf("endpoints API returned %d: %s", resp.StatusCode, string(body))
	}

	var ep endpointsResponse
	if err := json.NewDecoder(resp.Body).Decode(&ep); err != nil {
		return "", fmt.Errorf("decode endpoints: %w", err)
	}

	newMap := r.parseEndpoints(&ep)

	r.mu.Lock()
	old := r.nodeToAddr
	r.nodeToAddr = newMap
	r.mu.Unlock()

	r.logChanges(old, newMap)
	return ep.Metadata.ResourceVersion, nil
}

// parseEndpoints builds a node→addr map from an endpoints response.
func (r *NodeResolver) parseEndpoints(ep *endpointsResponse) map[string]string {
	newMap := make(map[string]string)
	for _, subset := range ep.Subsets {
		for _, addr := range subset.Addresses {
			if addr.NodeName != "" && addr.IP != "" {
				newMap[addr.NodeName] = fmt.Sprintf("%s:%d", addr.IP, r.port)
			}
		}
	}
	return newMap
}

// APIHost returns the K8s API server URL (for sharing with ResourceWatcher).
func (r *NodeResolver) APIHost() string { return r.apiHost }

// Token returns the service account token (for sharing with ResourceWatcher).
func (r *NodeResolver) Token() string { return r.token }

// HTTPClient returns a TLS-configured HTTP client suitable for K8s API calls.
// Shares the same TLS transport (cluster CA) as the NodeResolver.
func (r *NodeResolver) HTTPClient() *http.Client {
	return &http.Client{
		Timeout:   15 * time.Second,
		Transport: r.httpClient.Transport,
	}
}

// Resolve returns the gRPC address (podIP:port) for the given K8s node name.
// Returns empty string if unknown.
func (r *NodeResolver) Resolve(nodeName string) string {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.nodeToAddr[nodeName]
}

// NodeNames returns all known K8s node names.
func (r *NodeResolver) NodeNames() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()
	names := make([]string, 0, len(r.nodeToAddr))
	for name := range r.nodeToAddr {
		names = append(names, name)
	}
	return names
}

// ---------------------------------------------------------------------------
// Watch — replaces polling with a streaming K8s watch connection
// ---------------------------------------------------------------------------

// StartWatch starts a background goroutine that maintains a long-lived watch
// on the K8s Endpoints API. Changes are delivered in ~1s instead of 30s.
// onNodeChange is called after each map update (use for DiscoverNodes +
// RebuildRegistry). Stops when ctx is cancelled.
func (r *NodeResolver) StartWatch(ctx context.Context, onNodeChange func()) {
	go r.watchLoop(ctx, onNodeChange)
}

// watchLoop is the list-then-watch retry loop. On any failure it re-lists
// with exponential backoff (1s → 30s cap).
func (r *NodeResolver) watchLoop(ctx context.Context, onNodeChange func()) {
	backoff := time.Second
	const maxBackoff = 30 * time.Second

	for {
		if ctx.Err() != nil {
			return
		}

		// List to get current state + resourceVersion.
		rv, err := r.Refresh(ctx)
		if err != nil {
			klog.Warningf("NodeResolver: list failed: %v (retry in %v)", err, backoff)
			if !sleepCtx(ctx, backoff) {
				return
			}
			backoff = min(backoff*2, maxBackoff)
			continue
		}

		// Successful list resets backoff.
		backoff = time.Second

		if onNodeChange != nil {
			onNodeChange()
		}

		// Watch from the listed resourceVersion.
		if err := r.doWatch(ctx, rv, onNodeChange); err != nil {
			klog.Warningf("NodeResolver: watch disconnected: %v (re-listing)", err)
		}
	}
}

// doWatch opens a streaming watch connection and processes events until
// disconnect, context cancellation, or an unrecoverable error (410 Gone).
func (r *NodeResolver) doWatch(ctx context.Context, resourceVersion string, onNodeChange func()) error {
	url := fmt.Sprintf(
		"%s/api/v1/namespaces/%s/endpoints?watch=true&fieldSelector=metadata.name=%s&resourceVersion=%s&timeoutSeconds=300",
		r.apiHost, r.namespace, r.svcName, resourceVersion,
	)

	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return fmt.Errorf("create watch request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+r.token)
	req.Header.Set("Accept", "application/json")

	resp, err := r.watchClient.Do(req)
	if err != nil {
		return fmt.Errorf("watch API call: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
		return fmt.Errorf("watch API returned %d: %s", resp.StatusCode, string(body))
	}

	klog.V(2).Infof("NodeResolver: watch connected (rv=%s)", resourceVersion)

	scanner := bufio.NewScanner(resp.Body)
	// K8s watch events can be large; raise the default 64KB limit.
	scanner.Buffer(make([]byte, 0, 256*1024), 256*1024)

	for scanner.Scan() {
		if ctx.Err() != nil {
			return ctx.Err()
		}

		var event watchEvent
		if err := json.Unmarshal(scanner.Bytes(), &event); err != nil {
			klog.Warningf("NodeResolver: decode watch event: %v", err)
			continue
		}

		switch event.Type {
		case "ADDED", "MODIFIED":
			newMap := r.parseEndpoints(&event.Object)
			r.mu.Lock()
			old := r.nodeToAddr
			r.nodeToAddr = newMap
			r.mu.Unlock()

			r.logChanges(old, newMap)
			if onNodeChange != nil {
				onNodeChange()
			}

		case "DELETED":
			newMap := make(map[string]string)
			r.mu.Lock()
			old := r.nodeToAddr
			r.nodeToAddr = newMap
			r.mu.Unlock()

			r.logChanges(old, newMap)
			if onNodeChange != nil {
				onNodeChange()
			}

		case "ERROR":
			// 410 Gone means our resourceVersion is too old — need to re-list.
			return fmt.Errorf("watch ERROR event: %s", scanner.Text())
		}
	}

	if err := scanner.Err(); err != nil {
		return fmt.Errorf("watch stream: %w", err)
	}
	return fmt.Errorf("watch stream closed")
}

// logChanges logs node IP changes at info level for observability.
func (r *NodeResolver) logChanges(old, new map[string]string) {
	for name, addr := range new {
		oldAddr, existed := old[name]
		if !existed {
			klog.Infof("NodeResolver: node %s appeared (%s)", name, addr)
		} else if oldAddr != addr {
			klog.Infof("NodeResolver: node %s IP changed (%s → %s)", name, oldAddr, addr)
		}
	}
	for name := range old {
		if _, exists := new[name]; !exists {
			klog.Infof("NodeResolver: node %s removed", name)
		}
	}
	klog.V(2).Infof("NodeResolver: %d nodes in endpoints", len(new))
}

// sleepCtx sleeps for the given duration or until ctx is cancelled.
// Returns false if ctx was cancelled.
func sleepCtx(ctx context.Context, d time.Duration) bool {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-t.C:
		return true
	}
}

// ---------------------------------------------------------------------------
// K8s API response types
// ---------------------------------------------------------------------------

// endpointsResponse is a minimal struct for the K8s Endpoints API response.
type endpointsResponse struct {
	Metadata endpointsMeta    `json:"metadata"`
	Subsets  []endpointSubset `json:"subsets"`
}

type endpointsMeta struct {
	ResourceVersion string `json:"resourceVersion"`
}

type endpointSubset struct {
	Addresses []endpointAddress `json:"addresses"`
}

type endpointAddress struct {
	IP       string `json:"ip"`
	NodeName string `json:"nodeName"`
}

// watchEvent is a single event from the K8s watch stream.
type watchEvent struct {
	Type   string            `json:"type"` // ADDED, MODIFIED, DELETED, ERROR
	Object endpointsResponse `json:"object"`
}
