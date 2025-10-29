import React, { useState, useRef, useEffect } from 'react';
import { Outlet } from 'react-router-dom';

export default function Layout() {
  const [dividerPosition, setDividerPosition] = useState(400);
  const containerRef = useRef<HTMLDivElement>(null);
  const isDragging = useRef(false);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging.current || !containerRef.current) return;
      
      const containerRect = containerRef.current.getBoundingClientRect();
      const newPosition = e.clientX - containerRect.left;
      
      if (newPosition > 200 && newPosition < containerRect.width - 200) {
        setDividerPosition(newPosition);
      }
    };

    const handleMouseUp = () => {
      isDragging.current = false;
      document.body.style.cursor = 'default';
      document.body.style.userSelect = 'auto';
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, []);

  const handleMouseDown = () => {
    isDragging.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };

  return (
    <div ref={containerRef} className="h-screen flex bg-gray-900 text-white">
      <div style={{ width: `${dividerPosition}px` }} className="flex-shrink-0">
        <Outlet />
      </div>
      
      <div
        className="w-1 bg-gray-700 cursor-col-resize hover:bg-blue-500 transition-colors"
        onMouseDown={handleMouseDown}
      />
      
      <div className="flex-1 bg-gray-800">
        <div id="preview-container" className="h-full" />
      </div>
    </div>
  );
}