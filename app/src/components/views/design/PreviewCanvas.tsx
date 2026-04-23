import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  type ElementData,
  type DesignBridgeMessage,
  isDesignBridgeMessage,
  sendDesignMessage,
} from './DesignBridge';
import { CanvasViewport } from './CanvasViewport';

// ── Bridge status types ──────────────────────────────────────────
type BridgeStatus = 'not-installed' | 'connecting' | 'ready' | 'unavailable';

const BRIDGE_TIMEOUT_MS = 3000;
const STATUS_PILL_FADE_MS = 2000;

// Natural design-canvas size used when the user has selected "fit".
// The canvas transform handles visual fit via zoom, so the frame itself
// has a stable intrinsic size regardless of container dimensions.
const FIT_CANVAS_WIDTH = 1440;
const FIT_CANVAS_HEIGHT = 900;

export type DesignMode = 'select' | 'text' | 'move';

interface PreviewCanvasProps {
  devServerUrl: string;
  devServerUrlWithAuth: string;
  designMode: DesignMode;
  viewportWidth: number | 'fit';
  onElementSelect: (element: ElementData) => void;
  onElementHover: (element: ElementData | null) => void;
  onRefresh: () => void;
  bridgeInstalled: boolean;
  onInstallBridge: () => void;
}

export const PreviewCanvas: React.FC<PreviewCanvasProps> = ({
  devServerUrl: _devServerUrl,
  devServerUrlWithAuth,
  designMode,
  viewportWidth,
  onElementSelect,
  onElementHover,
  onRefresh: _onRefresh,
  bridgeInstalled,
  onInstallBridge,
}) => {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [bridgeStatus, setBridgeStatus] = useState<BridgeStatus>(
    bridgeInstalled ? 'connecting' : 'not-installed'
  );
  const [showReadyPill, setShowReadyPill] = useState(false);
  const [statusHovered, setStatusHovered] = useState(false);
  const bridgeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pillFadeRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const bridgeStatusRef = useRef<BridgeStatus>(bridgeStatus);

  // Keep ref in sync
  bridgeStatusRef.current = bridgeStatus;

  // ── Cleanup timeouts on unmount ────────────────────────────────
  useEffect(() => {
    return () => {
      if (bridgeTimeoutRef.current) clearTimeout(bridgeTimeoutRef.current);
      if (pillFadeRef.current) clearTimeout(pillFadeRef.current);
    };
  }, []);

  // ── Start bridge timeout ───────────────────────────────────────
  const startBridgeTimeout = useCallback(() => {
    if (bridgeTimeoutRef.current) clearTimeout(bridgeTimeoutRef.current);
    bridgeTimeoutRef.current = setTimeout(() => {
      setBridgeStatus((prev) => (prev === 'connecting' ? 'unavailable' : prev));
    }, BRIDGE_TIMEOUT_MS);
  }, []);

  // ── Sync bridgeInstalled prop to status ────────────────────────
  useEffect(() => {
    if (!bridgeInstalled) {
      setBridgeStatus('not-installed');
    } else if (
      bridgeStatusRef.current === 'not-installed' ||
      bridgeStatusRef.current === 'unavailable'
    ) {
      // Bridge was just installed or we need to retry — reload iframe so the script gets loaded
      setBridgeStatus('connecting');
      setTimeout(() => {
        const iframe = iframeRef.current;
        if (iframe) {
          const separator = devServerUrlWithAuth.includes('?') ? '&' : '?';
          iframe.src = `${devServerUrlWithAuth}${separator}t=${Date.now()}`;
        }
        startBridgeTimeout();
      }, 1500);
    }
  }, [bridgeInstalled, devServerUrlWithAuth, startBridgeTimeout]);

  // ── Handle bridge becoming ready ───────────────────────────────
  const markBridgeReady = useCallback(() => {
    if (bridgeTimeoutRef.current) {
      clearTimeout(bridgeTimeoutRef.current);
      bridgeTimeoutRef.current = null;
    }
    setBridgeStatus('ready');
    setShowReadyPill(true);
    if (pillFadeRef.current) clearTimeout(pillFadeRef.current);
    pillFadeRef.current = setTimeout(() => {
      setShowReadyPill(false);
    }, STATUS_PILL_FADE_MS);
  }, []);

  // ── Message handler for iframe responses ───────────────────────
  const handleMessage = useCallback(
    (event: MessageEvent) => {
      const { data } = event;

      // Handle url-change: bridge script reloads with the page
      if (data && typeof data === 'object' && data.type === 'url-change') {
        if (bridgeInstalled) {
          setBridgeStatus('connecting');
          startBridgeTimeout();
        }
        return;
      }

      if (!isDesignBridgeMessage(data)) return;

      const msg = data as DesignBridgeMessage;

      switch (msg.type) {
        case 'design:bridge-ready':
          markBridgeReady();
          break;

        case 'design:hover-data':
          if ('data' in msg) {
            onElementHover(msg.data);
          }
          break;

        case 'design:element-data':
          if ('data' in msg) {
            onElementSelect(msg.data);
          }
          break;
      }
    },
    [onElementSelect, onElementHover, markBridgeReady, startBridgeTimeout, bridgeInstalled]
  );

  useEffect(() => {
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [handleMessage]);

  // ── Handle iframe load: bridge is pre-installed, just wait for ready ──
  const handleIframeLoad = useCallback(() => {
    // If bridge is installed, start waiting for the bridge-ready message
    if (bridgeInstalled) {
      setBridgeStatus('connecting');
      startBridgeTimeout();
    }
    // If not installed, the sync effect above will handle installation + reload
  }, [bridgeInstalled, startBridgeTimeout]);

  // ── Send activate + mode when designMode or bridge status changes ──
  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe || bridgeStatus !== 'ready') return;

    sendDesignMessage(iframe, { type: 'design:activate' });
    sendDesignMessage(iframe, { type: 'design:set-mode', mode: designMode });
  }, [designMode, bridgeStatus]);

  // ── Retry handler ──────────────────────────────────────────────
  const handleRetry = useCallback(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    setBridgeStatus('connecting');
    startBridgeTimeout();
    // Reload the iframe to trigger the bridge script again
    const currentSrc = iframe.src;
    iframe.src = currentSrc;
  }, [startBridgeTimeout]);

  // ── Iframe source ──────────────────────────────────────────────
  const iframeSrc =
    devServerUrlWithAuth + (devServerUrlWithAuth.includes('?') ? '&' : '?') + '_r=1';

  // ── Viewport sizing ────────────────────────────────────────────
  // Inside CanvasViewport the frame is a transformed 0×0 container, so
  // we need explicit pixel dimensions. 'fit' resolves to a natural
  // design-canvas size and users lean on zoom (keyboard 0) to refit.
  const containerStyle: React.CSSProperties =
    viewportWidth === 'fit'
      ? { width: `${FIT_CANVAS_WIDTH}px`, height: `${FIT_CANVAS_HEIGHT}px` }
      : { width: `${viewportWidth}px`, height: `${FIT_CANVAS_HEIGHT}px` };

  // ── Status indicator (bottom-left) ─────────────────────────────
  const renderStatusIndicator = () => {
    const baseClasses =
      'absolute bottom-2 left-2 z-20 flex items-center gap-1.5 px-2 py-1 rounded-full text-[10px] backdrop-blur-sm border';

    if (bridgeStatus === 'not-installed') {
      return (
        <div
          className={baseClasses}
          style={{
            background: 'color-mix(in srgb, var(--surface, #1e1e1e) 85%, transparent)',
            borderColor: 'var(--border)',
          }}
        >
          <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: '#f97316' }} />
          <span style={{ color: 'var(--text-muted)' }}>Bridge needed</span>
          <button
            type="button"
            onClick={onInstallBridge}
            className="ml-1 px-1.5 py-0.5 rounded text-[9px] font-medium"
            style={{
              background: 'var(--primary)',
              color: '#fff',
            }}
          >
            Install
          </button>
        </div>
      );
    }

    if (bridgeStatus === 'connecting') {
      return (
        <div
          className={baseClasses}
          style={{
            background: 'color-mix(in srgb, var(--surface, #1e1e1e) 85%, transparent)',
            borderColor: 'var(--border)',
          }}
        >
          <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: '#eab308' }} />
          <span style={{ color: 'var(--text-muted)' }}>Connecting...</span>
        </div>
      );
    }

    if (bridgeStatus === 'ready') {
      const visible = showReadyPill || statusHovered;
      return (
        <div
          className={baseClasses}
          onMouseEnter={() => setStatusHovered(true)}
          onMouseLeave={() => setStatusHovered(false)}
          style={{
            background: 'color-mix(in srgb, var(--surface, #1e1e1e) 85%, transparent)',
            borderColor: 'var(--border)',
            opacity: visible ? 1 : 0,
            transition: 'opacity 0.3s ease',
            pointerEvents: 'auto',
          }}
        >
          <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: '#22c55e' }} />
          <span style={{ color: 'var(--text-muted)' }}>Design Mode</span>
        </div>
      );
    }

    if (bridgeStatus === 'unavailable') {
      return (
        <div
          className={baseClasses}
          style={{
            background: 'color-mix(in srgb, var(--surface, #1e1e1e) 85%, transparent)',
            borderColor: 'var(--border)',
          }}
        >
          <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: '#ef4444' }} />
          <span style={{ color: 'var(--text-muted)' }}>Unavailable</span>
          <button
            type="button"
            onClick={handleRetry}
            className="ml-1 px-1.5 py-0.5 rounded text-[9px] font-medium"
            style={{
              background: 'var(--surface)',
              color: 'var(--text-muted)',
              border: '1px solid var(--border)',
            }}
          >
            Retry
          </button>
        </div>
      );
    }

    return null;
  };

  return (
    <div className="relative w-full h-full bg-black overflow-hidden">
      <CanvasViewport>
        <div style={containerStyle} className="relative">
          <iframe
            id="design-preview-iframe"
            ref={iframeRef}
            src={iframeSrc}
            className="w-full h-full border-0"
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
            onLoad={handleIframeLoad}
            title="Design Preview"
          />
          {/*
            NO parent-side overlay. The bridge script inside the iframe handles all
            interaction (hover, click, drag, text edit) via its own overlay element.
            A parent overlay would block text editing focus and drag events from
            reaching the iframe. The bridge communicates results back via postMessage.
          */}
        </div>
      </CanvasViewport>

      {/* Install bridge prompt — centered over preview (not canvas-transformed). */}
      {bridgeStatus === 'not-installed' && (
        <div
          className="absolute inset-0 z-40 flex items-center justify-center"
          style={{ background: 'color-mix(in srgb, var(--bg, #000) 60%, transparent)' }}
        >
          <div
            className="flex flex-col items-center gap-3 px-6 py-5 rounded-lg border shadow-xl"
            style={{
              background: 'var(--surface)',
              borderColor: 'var(--border)',
            }}
          >
            <p className="text-sm font-medium" style={{ color: 'var(--text)' }}>
              Design bridge is not installed in this project
            </p>
            <p className="text-xs max-w-[280px] text-center" style={{ color: 'var(--text-muted)' }}>
              The design bridge enables element inspection, style editing, and live preview
              interactions.
            </p>
            <button
              type="button"
              onClick={onInstallBridge}
              className="px-4 py-1.5 rounded-md text-xs font-medium cursor-pointer hover:opacity-90 transition-opacity"
              style={{
                background: 'var(--primary)',
                color: '#fff',
              }}
            >
              Install Design Bridge
            </button>
          </div>
        </div>
      )}

      {/* Reconnecting pill — stays in viewport space, not canvas space. */}
      {bridgeStatus === 'unavailable' && (
        <div
          className="absolute top-2 left-1/2 -translate-x-1/2 z-20 px-3 py-1 rounded-full text-[10px] backdrop-blur-sm border"
          style={{
            background: 'color-mix(in srgb, var(--surface, #1e1e1e) 85%, transparent)',
            borderColor: 'var(--border)',
            color: 'var(--text-muted)',
          }}
        >
          Reconnecting...
        </div>
      )}

      {/* Status indicator (bottom-left corner) */}
      {renderStatusIndicator()}
    </div>
  );
};

export default PreviewCanvas;
