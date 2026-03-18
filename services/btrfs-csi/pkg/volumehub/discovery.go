package volumehub

import (
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
// It queries the K8s Endpoints API using the in-cluster service account token —
// no client-go dependency, just net/http.
type NodeResolver struct {
	mu         sync.RWMutex
	nodeToAddr map[string]string // K8s node name → podIP:port
	svcName    string            // headless service name (e.g. "tesslate-btrfs-csi-node-svc")
	namespace  string            // namespace of the service (e.g. "kube-system")
	port       int               // NodeOps gRPC port on the CSI node pods
	apiHost    string            // K8s API server host (from KUBERNETES_SERVICE_HOST)
	token      string            // service account token
	httpClient *http.Client
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

	return &NodeResolver{
		nodeToAddr: make(map[string]string),
		svcName:    svcName,
		namespace:  namespace,
		port:       port,
		apiHost:    fmt.Sprintf("https://%s:%s", apiHost, apiPort),
		token:      string(tokenBytes),
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
			Transport: &http.Transport{
				TLSClientConfig: tlsCfg,
			},
		},
	}, nil
}

// Refresh queries the K8s Endpoints API and updates the node→addr map.
func (r *NodeResolver) Refresh(ctx context.Context) error {
	url := fmt.Sprintf("%s/api/v1/namespaces/%s/endpoints/%s", r.apiHost, r.namespace, r.svcName)

	req, err := http.NewRequestWithContext(ctx, "GET", url, nil)
	if err != nil {
		return fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+r.token)
	req.Header.Set("Accept", "application/json")

	resp, err := r.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("endpoints API call: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
		return fmt.Errorf("endpoints API returned %d: %s", resp.StatusCode, string(body))
	}

	var ep endpointsResponse
	if err := json.NewDecoder(resp.Body).Decode(&ep); err != nil {
		return fmt.Errorf("decode endpoints: %w", err)
	}

	newMap := make(map[string]string)
	for _, subset := range ep.Subsets {
		for _, addr := range subset.Addresses {
			if addr.NodeName != "" && addr.IP != "" {
				newMap[addr.NodeName] = fmt.Sprintf("%s:%d", addr.IP, r.port)
			}
		}
	}

	r.mu.Lock()
	r.nodeToAddr = newMap
	r.mu.Unlock()

	klog.V(2).Infof("NodeResolver: refreshed %d nodes from endpoints/%s", len(newMap), r.svcName)
	return nil
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

// StartPeriodicRefresh runs Refresh every interval in a background goroutine.
// Stops when ctx is cancelled.
func (r *NodeResolver) StartPeriodicRefresh(ctx context.Context, interval time.Duration) {
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				if err := r.Refresh(ctx); err != nil {
					klog.Warningf("NodeResolver periodic refresh: %v", err)
				}
			}
		}
	}()
}

// endpointsResponse is a minimal struct for the K8s Endpoints API response.
// Only the fields we need are decoded.
type endpointsResponse struct {
	Subsets []endpointSubset `json:"subsets"`
}

type endpointSubset struct {
	Addresses []endpointAddress `json:"addresses"`
}

type endpointAddress struct {
	IP       string `json:"ip"`
	NodeName string `json:"nodeName"`
}

