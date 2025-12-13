import React, { useEffect, useRef } from 'react';
import gsap from 'gsap';

interface PreloaderProps {
  onComplete?: () => void;
}

export function Preloader({ onComplete }: PreloaderProps) {
  const preloaderRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Custom ease for stutter effect
    const customEase = 'M0,0 C0,0 0.052,0.1 0.152,0.1 0.242,0.1 0.299,0.349 0.399,0.349 0.586,0.349 0.569,0.596 0.67,0.624 0.842,0.671 0.95,0.95 1,1';

    const tl = gsap.timeline({
      onComplete: () => {
        setTimeout(() => {
          onComplete?.();
        }, 300);
      },
    });

    // Animate background bar
    tl.to('.preloader-bg', {
      scaleX: 1,
      ease: customEase,
      duration: 2.8,
    })
      // Scale up mask
      .to('.preloader-mask', {
        scale: 3,
        duration: 0.9,
        ease: 'power1.in',
      })
      // Fade out everything
      .to(
        '.preloader-bg, .preloader-progress-bar',
        {
          opacity: 0,
          duration: 0.85,
          ease: 'power2.inOut',
        },
        '<'
      )
      .to('.preloader-container', {
        opacity: 0,
        duration: 0.3,
        pointerEvents: 'none',
      });

    return () => {
      tl.kill();
    };
  }, [onComplete]);

  return (
    <div ref={preloaderRef} className="preloader-container">
      <div className="preloader-mask"></div>
      <div className="preloader-progress-bar">
        <div className="preloader-bg"></div>
      </div>

      <style>{`
        .preloader-container {
          position: fixed;
          top: 0;
          left: 0;
          width: 100%;
          height: 100vh;
          z-index: 9999;
          pointer-events: all;
        }

        .preloader-mask,
        .preloader-progress-bar,
        .preloader-bg {
          position: fixed;
          top: 0;
          left: 0;
          height: 100vh;
          width: 100%;
          pointer-events: none;
        }

        .preloader-mask {
          z-index: 10002;
          background-color: #0a0a0a;
          -webkit-mask: linear-gradient(white, white), url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYxLjkiIGhlaWdodD0iMTI2LjY2IiB2aWV3Qm94PSIwIDAgMTYxLjkgMTI2LjY2IiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjxnPjxwYXRoIGQ9Im0xMy40NSw0Ni40OGg1NC4wNmMxMC4yMSwwLDE2LjY4LTEwLjk0LDExLjc3LTE5Ljg5bC05LjE5LTE2Ljc1Yy0yLjM2LTQuMy02Ljg3LTYuOTctMTEuNzctNi45N0gyMi40MWMtNC45NSwwLTkuNSwyLjczLTExLjg0LDcuMDlMMS42MSwyNi43MWMtNC43OSw4Ljk1LDEuNjksMTkuNzcsMTEuODQsMTkuNzdaIiBmaWxsPSIjZmY2YjAwIiBzdHJva2Utd2lkdGg9IjAiLz48cGF0aCBkPSJtNjEuMDUsMTE5LjkzbDI2Ljk1LTQ2Ljg2YzUuMDktOC44NS0xLjE3LTE5LjkxLTExLjM3LTIwLjEybC0xOS4xMS0uMzhjLTQuOS0uMS05LjQ3LDIuNDgtMTEuOTEsNi43M2wtMTcuODksMzEuMTJjLTIuNDcsNC4yOS0yLjM3LDkuNi4yNSwxMy44bDEwLjA1LDE2LjEzYzUuMzcsOC42MSwxNy45OCw4LjM5LDIzLjA0LS40MVoiIGZpbGw9IiNmZjZiMDAiIHN0cm9rZS13aWR0aD0iMCIvPjxwYXRoIGQ9Im0xNDguNDYsMGgtNTQuMDZjLTEwLjIxLDAtMTYuNjgsMTAuOTQtMTEuNzcsMTkuODlsOS4xOSwxNi43NWMyLjM2LDQuMyw2Ljg3LDYuOTcsMTEuNzcsNi45N2gzNS45YzQuOTUsMCw5LjUtMi43MywxMS44NC03LjA5bDguOTctMTYuNzVDMTY1LjA4LDEwLjgyLDE1OC42LDAsMTQ4LjQ2LDBaIiBmaWxsPSIjZmY2YjAwIiBzdHJva2Utd2lkdGg9IjAiLz48L2c+PC9zdmc+') center/40% no-repeat;
          mask: linear-gradient(white, white), url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYxLjkiIGhlaWdodD0iMTI2LjY2IiB2aWV3Qm94PSIwIDAgMTYxLjkgMTI2LjY2IiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjxnPjxwYXRoIGQ9Im0xMy40NSw0Ni40OGg1NC4wNmMxMC4yMSwwLDE2LjY4LTEwLjk0LDExLjc3LTE5Ljg5bC05LjE5LTE2Ljc1Yy0yLjM2LTQuMy02Ljg3LTYuOTctMTEuNzctNi45N0gyMi40MWMtNC45NSwwLTkuNSwyLjczLTExLjg0LDcuMDlMMS42MSwyNi43MWMtNC43OSw4Ljk1LDEuNjksMTkuNzcsMTEuODQsMTkuNzdaIiBmaWxsPSIjZmY2YjAwIiBzdHJva2Utd2lkdGg9IjAiLz48cGF0aCBkPSJtNjEuMDUsMTE5LjkzbDI2Ljk1LTQ2Ljg2YzUuMDktOC44NS0xLjE3LTE5LjkxLTExLjM3LTIwLjEybC0xOS4xMS0uMzhjLTQuOS0uMS05LjQ3LDIuNDgtMTEuOTEsNi43M2wtMTcuODksMzEuMTJjLTIuNDcsNC4yOS0yLjM3LDkuNi4yNSwxMy44bDEwLjA1LDE2LjEzYzUuMzcsOC42MSwxNy45OCw4LjM5LDIzLjA0LS40MVoiIGZpbGw9IiNmZjZiMDAiIHN0cm9rZS13aWR0aD0iMCIvPjxwYXRoIGQ9Im0xNDguNDYsMGgtNTQuMDZjLTEwLjIxLDAtMTYuNjgsMTAuOTQtMTEuNzcsMTkuODlsOS4xOSwxNi43NWMyLjM2LDQuMyw2Ljg3LDYuOTcsMTEuNzcsNi45N2gzNS45YzQuOTUsMCw5LjUtMi43MywxMS44NC03LjA5bDguOTctMTYuNzVDMTY1LjA4LDEwLjgyLDE1OC42LDAsMTQ4LjQ2LDBaIiBmaWxsPSIjZmY2YjAwIiBzdHJva2Utd2lkdGg9IjAiLz48L2c+PC9zdmc+') center/40% no-repeat;
          -webkit-mask-composite: source-out;
          mask-composite: subtract;
        }

        .preloader-progress-bar {
          width: 100%;
          height: 100%;
          z-index: 10001;
          background-color: #000000;
        }

        .preloader-bg {
          background: linear-gradient(90deg, #FF6B00 0%, #ff8533 50%, #FF6B00 100%);
          transform-origin: left;
          transform: scaleX(0.2);
          box-shadow: 0 0 20px rgba(255, 107, 0, 0.5);
        }
      `}</style>
    </div>
  );
}
