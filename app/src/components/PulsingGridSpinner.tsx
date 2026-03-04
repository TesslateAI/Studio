import React, { useEffect, useRef } from 'react';

interface PulsingGridSpinnerProps {
  size?: number;
  className?: string;
}

export const PulsingGridSpinner: React.FC<PulsingGridSpinnerProps> = ({
  size = 60,
  className = ''
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animationIdRef = useRef<number | undefined>(undefined);
  const lastTimeRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Store canvas and ctx in constants that TypeScript knows are non-null
    const canvasElement = canvas;
    const context = ctx;

    const scale = size / 60; // Base size is 60px
    canvasElement.width = size;
    canvasElement.height = size;

    const centerX = canvasElement.width / 2;
    const centerY = canvasElement.height / 2;
    let time = 0;

    // Grid parameters
    const gridSize = 5; // 5x5 grid
    const spacing = 5 * scale;

    // Animation parameters
    const breathingSpeed = 0.5; // Speed of expansion/contraction
    const colorPulseSpeed = 1.0; // Speed of color pulsing

    // Define middle 8 positions (surrounding center in a 5x5 grid)
    const middleEight = [
      { row: 1, col: 2 }, // top
      { row: 2, col: 1 }, // left
      { row: 2, col: 3 }, // right
      { row: 3, col: 2 }, // bottom
      { row: 1, col: 1 }, // top-left
      { row: 1, col: 3 }, // top-right
      { row: 3, col: 1 }, // bottom-left
      { row: 3, col: 3 }, // bottom-right
    ];

    const isMiddleEight = (row: number, col: number) => {
      return middleEight.some(pos => pos.row === row && pos.col === col);
    };

    function animate(timestamp: number) {
      if (!lastTimeRef.current) lastTimeRef.current = timestamp;
      const deltaTime = timestamp - lastTimeRef.current;
      lastTimeRef.current = timestamp;
      time += deltaTime * 0.001;

      context.clearRect(0, 0, canvasElement.width, canvasElement.height);

      // Calculate breathing effect - grid expands and contracts
      const breathingFactor = Math.sin(time * breathingSpeed) * 0.2 + 1.0; // 0.8 to 1.2

      // Draw center dot
      context.beginPath();
      context.arc(centerX, centerY, 1.5 * scale, 0, Math.PI * 2);
      context.fillStyle = "rgba(255, 107, 0, 0.9)"; // Orange center
      context.fill();

      // Draw pulsing grid pattern
      for (let row = 0; row < gridSize; row++) {
        for (let col = 0; col < gridSize; col++) {
          // Skip center point
          if (row === Math.floor(gridSize / 2) && col === Math.floor(gridSize / 2))
            continue;

          // Calculate base position
          const baseX = (col - (gridSize - 1) / 2) * spacing;
          const baseY = (row - (gridSize - 1) / 2) * spacing;

          // Calculate distance and angle from center for effects
          const distance = Math.sqrt(baseX * baseX + baseY * baseY);
          const maxDistance = (spacing * Math.sqrt(2) * (gridSize - 1)) / 2;
          const normalizedDistance = distance / maxDistance;
          const angle = Math.atan2(baseY, baseX);

          // Apply complex wave effects
          // 1. Radial wave (expands from center)
          const radialPhase = (time - normalizedDistance) % 1;
          const radialWave = Math.sin(radialPhase * Math.PI * 2) * 2 * scale;

          // 2. Breathing effect (entire grid expands/contracts)
          const breathingX = baseX * breathingFactor;
          const breathingY = baseY * breathingFactor;

          // Combine all effects
          const waveX = centerX + breathingX + Math.cos(angle) * radialWave;
          const waveY = centerY + breathingY + Math.sin(angle) * radialWave;

          // Dot size varies with distance and time
          const baseSize = (0.8 + (1 - normalizedDistance) * 0.7) * scale;
          const pulseFactor = Math.sin(time * 2 + normalizedDistance * 5) * 0.6 + 1;
          const dotSize = baseSize * pulseFactor;

          // Check if this is one of the middle 8
          const isMiddle = isMiddleEight(row, col);

          let r, g, b;
          if (isMiddle) {
            // Orange color for middle 8 (#FF6B00)
            const orangePulse = Math.sin(time * colorPulseSpeed + normalizedDistance * 3) * 0.2 + 0.8;
            r = 255;
            g = Math.floor(107 * orangePulse);
            b = 0;
          } else {
            // White/light blue for outer dots
            const blueAmount = Math.sin(time * colorPulseSpeed + normalizedDistance * 3) * 0.3 + 0.3;
            const whiteness = 1 - blueAmount;
            r = Math.floor(255 * whiteness + 200 * blueAmount);
            g = Math.floor(255 * whiteness + 220 * blueAmount);
            b = 255;
          }

          // Calculate opacity with subtle pulse
          const opacity = 0.5 + Math.sin(time * 1.5 + angle * 3) * 0.2 + normalizedDistance * 0.3;

          // Draw connecting lines to create a network effect (optional, subtle)
          if (row > 0 && col > 0 && row < gridSize - 1 && col < gridSize - 1) {
            const neighbors = [
              { r: row - 1, c: col }, // top
              { r: row, c: col + 1 }, // right
            ];
            for (const neighbor of neighbors) {
              if (neighbor.r === Math.floor(gridSize / 2) && neighbor.c === Math.floor(gridSize / 2))
                continue;

              const nBaseX = (neighbor.c - (gridSize - 1) / 2) * spacing;
              const nBaseY = (neighbor.r - (gridSize - 1) / 2) * spacing;
              const nBreathingX = nBaseX * breathingFactor;
              const nBreathingY = nBaseY * breathingFactor;

              const lineDistance = Math.sqrt(Math.pow(col - neighbor.c, 2) + Math.pow(row - neighbor.r, 2));
              const lineOpacity = 0.05 + Math.sin(time * 1.5 + lineDistance * 2) * 0.03;

              context.beginPath();
              context.moveTo(waveX, waveY);
              context.lineTo(centerX + nBreathingX, centerY + nBreathingY);
              context.strokeStyle = isMiddle && isMiddleEight(neighbor.r, neighbor.c)
                ? `rgba(255, 107, 0, ${lineOpacity})`
                : `rgba(255, 255, 255, ${lineOpacity})`;
              context.lineWidth = 0.3 * scale;
              context.stroke();
            }
          }

          // Draw dot
          context.beginPath();
          context.arc(waveX, waveY, dotSize, 0, Math.PI * 2);
          context.fillStyle = `rgba(${r}, ${g}, ${b}, ${opacity})`;
          context.fill();
        }
      }
      animationIdRef.current = requestAnimationFrame(animate);
    }

    animationIdRef.current = requestAnimationFrame(animate);

    // Cleanup
    return () => {
      if (animationIdRef.current) {
        cancelAnimationFrame(animationIdRef.current);
      }
    };
  }, [size]);

  return (
    <div className={`inline-flex items-center justify-center ${className}`}>
      <canvas
        ref={canvasRef}
        className="block"
        style={{ width: size, height: size }}
      />
    </div>
  );
};

// Default loading component that can be used as a drop-in replacement
export const LoadingSpinner: React.FC<{
  message?: string;
  size?: number;
  className?: string;
}> = ({ message, size = 60, className = '' }) => {
  return (
    <div className={`flex flex-col items-center justify-center gap-4 ${className}`}>
      <PulsingGridSpinner size={size} />
      {message && (
        <p className="text-[var(--text)] text-sm font-medium animate-pulse">{message}</p>
      )}
    </div>
  );
};

// Full screen loading overlay
export const LoadingOverlay: React.FC<{
  message?: string;
  visible?: boolean;
}> = ({ message = 'Loading...', visible = true }) => {
  if (!visible) return null;

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center">
      <div className="bg-[var(--bg-primary)] rounded-2xl p-8 shadow-2xl">
        <LoadingSpinner message={message} size={80} />
      </div>
    </div>
  );
};