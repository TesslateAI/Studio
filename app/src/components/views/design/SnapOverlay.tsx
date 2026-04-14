/**
 * Snap Overlay — renders active snap guidelines as SVG lines.
 *
 * Guidelines live in canvas (world) coordinates and are transformed by
 * the same matrix as the frame so they track the iframe under zoom/pan.
 * This component is absolutely positioned full-size inside
 * CanvasViewport with pointer-events disabled — it's a pure visual layer.
 */

import React from 'react';
import { useCanvasStore } from './canvasStore';

const LINE_COLOR = 'rgba(239, 68, 68, 0.85)';
const LINE_GLOW = '0 0 4px rgba(239, 68, 68, 0.55)';

export const SnapOverlay: React.FC = () => {
  const snapLines = useCanvasStore((s) => s.snapLines);
  const x = useCanvasStore((s) => s.position.x);
  const y = useCanvasStore((s) => s.position.y);
  const scale = useCanvasStore((s) => s.scale);
  const transform = `translate(${x}px, ${y}px) scale(${scale})`;

  if (snapLines.length === 0) return null;

  return (
    <div
      className="absolute inset-0 pointer-events-none z-30"
      style={{ overflow: 'visible' }}
      aria-hidden
    >
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 0,
          width: 0,
          height: 0,
          transformOrigin: '0 0',
          transform,
        }}
      >
        <svg
          width="1"
          height="1"
          style={{ overflow: 'visible', position: 'absolute', left: 0, top: 0 }}
        >
          {snapLines.map((line) => {
            const isVertical = line.orientation === 'vertical';
            // Draw lines with 0 width so they stay 1px under any zoom
            // level — rely on `vectorEffect="non-scaling-stroke"`.
            const x1 = isVertical ? line.position : line.start;
            const y1 = isVertical ? line.start : line.position;
            const x2 = isVertical ? line.position : line.end;
            const y2 = isVertical ? line.end : line.position;
            return (
              <line
                key={line.id}
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                stroke={LINE_COLOR}
                strokeWidth={1}
                vectorEffect="non-scaling-stroke"
                strokeDasharray={line.type === 'center' ? '4 4' : undefined}
                style={{ filter: `drop-shadow(${LINE_GLOW})` }}
              />
            );
          })}
        </svg>
      </div>
    </div>
  );
};

export default SnapOverlay;
