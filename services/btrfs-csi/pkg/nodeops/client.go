package nodeops

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"os"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"
	"k8s.io/klog/v2"
)

// Client implements NodeOps by forwarding calls to a remote node's gRPC server.
type Client struct {
	conn *grpc.ClientConn
}

// NewClient connects to the nodeops gRPC server at the given address.
// Uses mTLS when tlsCfg is provided, otherwise uses system certificate pool.
func NewClient(addr string, tlsCfg *TLSConfig) (*Client, error) {
	creds, err := loadClientTLS(tlsCfg)
	if err != nil {
		return nil, fmt.Errorf("nodeops client TLS: %w", err)
	}

	opts := []grpc.DialOption{
		grpc.WithTransportCredentials(creds),
		grpc.WithDefaultCallOptions(grpc.ForceCodec(jsonCodec{})),
	}

	klog.V(2).Infof("NodeOps client connecting to %s", addr)

	conn, err := grpc.NewClient(addr, opts...)
	if err != nil {
		return nil, fmt.Errorf("connect to nodeops at %s: %w", addr, err)
	}

	return &Client{conn: conn}, nil
}

// NewClientWithDialOptions creates a nodeops client with custom gRPC dial options.
// This is useful for testing with plaintext connections (grpc.WithTransportCredentials(insecure.NewCredentials())).
func NewClientWithDialOptions(addr string, opts ...grpc.DialOption) (*Client, error) {
	opts = append(opts, grpc.WithDefaultCallOptions(grpc.ForceCodec(jsonCodec{})))
	conn, err := grpc.NewClient(addr, opts...)
	if err != nil {
		return nil, fmt.Errorf("connect to nodeops at %s: %w", addr, err)
	}
	return &Client{conn: conn}, nil
}

// loadClientTLS returns transport credentials appropriate for the config:
//   - cfg == nil: plaintext (for cluster-internal traffic protected by NetworkPolicy)
//   - cfg with CertFile: mutual TLS
//   - cfg without CertFile but with CAFile: server-auth TLS
func loadClientTLS(cfg *TLSConfig) (credentials.TransportCredentials, error) {
	// No TLS config → plaintext, matching server behavior when no certs are provided.
	if cfg == nil {
		return insecure.NewCredentials(), nil
	}

	tlsConfig := &tls.Config{
		MinVersion: tls.VersionTLS13,
	}

	// Load client certificate for mTLS if provided.
	if cfg.CertFile != "" {
		if _, err := os.Stat(cfg.CertFile); err == nil {
			cert, err := tls.LoadX509KeyPair(cfg.CertFile, cfg.KeyFile)
			if err != nil {
				return nil, fmt.Errorf("load client key pair: %w", err)
			}
			tlsConfig.Certificates = []tls.Certificate{cert}
		}
	}

	// Load custom CA if provided.
	if cfg.CAFile != "" {
		caPEM, err := os.ReadFile(cfg.CAFile)
		if err != nil {
			return nil, fmt.Errorf("read CA file: %w", err)
		}
		pool := x509.NewCertPool()
		if !pool.AppendCertsFromPEM(caPEM) {
			return nil, fmt.Errorf("failed to parse CA certificate")
		}
		tlsConfig.RootCAs = pool
	}

	return credentials.NewTLS(tlsConfig), nil
}

// Close closes the underlying gRPC connection.
func (c *Client) Close() error {
	return c.conn.Close()
}

// invoke is a helper that calls a nodeops RPC method.
func (c *Client) invoke(ctx context.Context, method string, req, resp interface{}) error {
	return c.conn.Invoke(ctx, "/nodeops.NodeOps/"+method, req, resp)
}

func (c *Client) CreateSubvolume(ctx context.Context, name string) error {
	return c.invoke(ctx, "CreateSubvolume", &SubvolumeRequest{Name: name}, &Empty{})
}

func (c *Client) DeleteSubvolume(ctx context.Context, name string) error {
	return c.invoke(ctx, "DeleteSubvolume", &SubvolumeRequest{Name: name}, &Empty{})
}

func (c *Client) SnapshotSubvolume(ctx context.Context, source, dest string, readOnly bool) error {
	return c.invoke(ctx, "SnapshotSubvolume", &SubvolumeRequest{Source: source, Dest: dest, ReadOnly: readOnly}, &Empty{})
}

func (c *Client) SubvolumeExists(ctx context.Context, name string) (bool, error) {
	var resp SubvolumeExistsResponse
	if err := c.invoke(ctx, "SubvolumeExists", &SubvolumeRequest{Name: name}, &resp); err != nil {
		return false, err
	}
	return resp.Exists, nil
}

func (c *Client) GetCapacity(ctx context.Context) (int64, int64, error) {
	var resp CapacityResponse
	if err := c.invoke(ctx, "GetCapacity", &Empty{}, &resp); err != nil {
		return 0, 0, err
	}
	return resp.Total, resp.Available, nil
}

func (c *Client) ListSubvolumes(ctx context.Context, prefix string) ([]SubvolumeInfo, error) {
	var resp ListSubvolumesResponse
	if err := c.invoke(ctx, "ListSubvolumes", &SubvolumeRequest{Prefix: prefix}, &resp); err != nil {
		return nil, err
	}
	return resp.Subvolumes, nil
}

func (c *Client) TrackVolume(ctx context.Context, volumeID string) error {
	return c.invoke(ctx, "TrackVolume", &VolumeTrackRequest{VolumeID: volumeID}, &Empty{})
}

func (c *Client) UntrackVolume(ctx context.Context, volumeID string) error {
	return c.invoke(ctx, "UntrackVolume", &VolumeTrackRequest{VolumeID: volumeID}, &Empty{})
}

func (c *Client) EnsureTemplate(ctx context.Context, name string) error {
	return c.invoke(ctx, "EnsureTemplate", &TemplateRequest{Name: name}, &Empty{})
}

func (c *Client) RestoreVolume(ctx context.Context, volumeID string) error {
	return c.invoke(ctx, "RestoreVolume", &VolumeTrackRequest{VolumeID: volumeID}, &Empty{})
}

func (c *Client) PromoteToTemplate(ctx context.Context, volumeID, templateName string) error {
	return c.invoke(ctx, "PromoteToTemplate", &PromoteTemplateRequest{
		VolumeID: volumeID, TemplateName: templateName,
	}, &Empty{})
}
