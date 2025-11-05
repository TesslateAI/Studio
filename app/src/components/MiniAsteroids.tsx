import React, { useEffect, useRef, useState } from 'react';

interface Vector {
  x: number;
  y: number;
}

interface Asteroid {
  pos: Vector;
  vel: Vector;
  radius: number;
  points: Vector[];
}

interface Bullet {
  pos: Vector;
  vel: Vector;
  life: number;
}

export function MiniAsteroids() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [score, setScore] = useState(0);
  const [gameOver, setGameOver] = useState(false);
  const gameStateRef = useRef({
    ship: { pos: { x: 0, y: 0 }, vel: { x: 0, y: 0 }, angle: 0 },
    asteroids: [] as Asteroid[],
    bullets: [] as Bullet[],
    keys: {} as Record<string, boolean>,
    lastTime: 0,
    invulnerable: 0,
  });

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Set canvas size
    const resizeCanvas = () => {
      const container = canvas.parentElement;
      if (container) {
        canvas.width = container.clientWidth;
        canvas.height = container.clientHeight;

        // Initialize ship position at center
        if (gameStateRef.current.ship.pos.x === 0) {
          gameStateRef.current.ship.pos = {
            x: canvas.width / 2,
            y: canvas.height / 2,
          };
        }
      }
    };
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

    // Generate random asteroid
    const createAsteroid = (x?: number, y?: number, radius = 30): Asteroid => {
      const pos = x !== undefined && y !== undefined
        ? { x, y }
        : {
            x: Math.random() * canvas.width,
            y: Math.random() * canvas.height,
          };

      const angle = Math.random() * Math.PI * 2;
      const speed = 30 + Math.random() * 30;
      const vel = {
        x: Math.cos(angle) * speed,
        y: Math.sin(angle) * speed,
      };

      // Generate irregular shape
      const points: Vector[] = [];
      const numPoints = 8 + Math.floor(Math.random() * 4);
      for (let i = 0; i < numPoints; i++) {
        const angle = (i / numPoints) * Math.PI * 2;
        const r = radius * (0.7 + Math.random() * 0.3);
        points.push({
          x: Math.cos(angle) * r,
          y: Math.sin(angle) * r,
        });
      }

      return { pos, vel, radius, points };
    };

    // Initialize asteroids
    const initGame = () => {
      gameStateRef.current.asteroids = [];
      for (let i = 0; i < 5; i++) {
        gameStateRef.current.asteroids.push(createAsteroid());
      }
      gameStateRef.current.bullets = [];
      gameStateRef.current.ship.vel = { x: 0, y: 0 };
      gameStateRef.current.ship.angle = 0;
      gameStateRef.current.invulnerable = 120; // 2 seconds of invulnerability
      setScore(0);
      setGameOver(false);
    };
    initGame();

    // Keyboard controls
    const handleKeyDown = (e: KeyboardEvent) => {
      gameStateRef.current.keys[e.key] = true;
      if (e.key === ' ' || e.key === 'ArrowUp' || e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        e.preventDefault();
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      gameStateRef.current.keys[e.key] = false;
    };

    // Touch/Mouse controls for mobile
    const handlePointerDown = (e: PointerEvent) => {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      // Left side = rotate left, right side = rotate right, center = thrust/shoot
      const third = canvas.width / 3;
      if (x < third) {
        gameStateRef.current.keys['ArrowLeft'] = true;
      } else if (x > third * 2) {
        gameStateRef.current.keys['ArrowRight'] = true;
      } else {
        gameStateRef.current.keys['ArrowUp'] = true;
        gameStateRef.current.keys[' '] = true;
      }
    };

    const handlePointerUp = () => {
      gameStateRef.current.keys = {};
    };

    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('keyup', handleKeyUp);
    canvas.addEventListener('pointerdown', handlePointerDown);
    canvas.addEventListener('pointerup', handlePointerUp);
    canvas.addEventListener('pointerleave', handlePointerUp);

    // Game loop
    let animationFrame: number;
    const gameLoop = (timestamp: number) => {
      const dt = gameStateRef.current.lastTime ? (timestamp - gameStateRef.current.lastTime) / 1000 : 0;
      gameStateRef.current.lastTime = timestamp;

      if (!ctx || gameOver) return;

      const { ship, asteroids, bullets, keys } = gameStateRef.current;

      // Clear canvas
      ctx.fillStyle = 'rgba(10, 10, 15, 0.3)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      // Update ship
      if (keys['ArrowLeft']) ship.angle -= 5 * dt * 60;
      if (keys['ArrowRight']) ship.angle += 5 * dt * 60;
      if (keys['ArrowUp']) {
        ship.vel.x += Math.cos(ship.angle) * 200 * dt;
        ship.vel.y += Math.sin(ship.angle) * 200 * dt;
      }

      // Friction
      ship.vel.x *= 0.99;
      ship.vel.y *= 0.99;

      // Update ship position
      ship.pos.x += ship.vel.x * dt;
      ship.pos.y += ship.vel.y * dt;

      // Wrap around screen
      if (ship.pos.x < 0) ship.pos.x = canvas.width;
      if (ship.pos.x > canvas.width) ship.pos.x = 0;
      if (ship.pos.y < 0) ship.pos.y = canvas.height;
      if (ship.pos.y > canvas.height) ship.pos.y = 0;

      // Shoot
      if (keys[' '] && bullets.length < 5) {
        bullets.push({
          pos: { ...ship.pos },
          vel: {
            x: Math.cos(ship.angle) * 300 + ship.vel.x,
            y: Math.sin(ship.angle) * 300 + ship.vel.y,
          },
          life: 60,
        });
        keys[' '] = false; // Prevent auto-fire
      }

      // Update bullets
      for (let i = bullets.length - 1; i >= 0; i--) {
        const bullet = bullets[i];
        bullet.pos.x += bullet.vel.x * dt;
        bullet.pos.y += bullet.vel.y * dt;
        bullet.life--;

        // Wrap around
        if (bullet.pos.x < 0) bullet.pos.x = canvas.width;
        if (bullet.pos.x > canvas.width) bullet.pos.x = 0;
        if (bullet.pos.y < 0) bullet.pos.y = canvas.height;
        if (bullet.pos.y > canvas.height) bullet.pos.y = 0;

        if (bullet.life <= 0) {
          bullets.splice(i, 1);
        }
      }

      // Update asteroids
      for (let i = asteroids.length - 1; i >= 0; i--) {
        const asteroid = asteroids[i];
        asteroid.pos.x += asteroid.vel.x * dt;
        asteroid.pos.y += asteroid.vel.y * dt;

        // Wrap around
        if (asteroid.pos.x < -asteroid.radius) asteroid.pos.x = canvas.width + asteroid.radius;
        if (asteroid.pos.x > canvas.width + asteroid.radius) asteroid.pos.x = -asteroid.radius;
        if (asteroid.pos.y < -asteroid.radius) asteroid.pos.y = canvas.height + asteroid.radius;
        if (asteroid.pos.y > canvas.height + asteroid.radius) asteroid.pos.y = -asteroid.radius;

        // Check collision with bullets
        for (let j = bullets.length - 1; j >= 0; j--) {
          const bullet = bullets[j];
          const dx = asteroid.pos.x - bullet.pos.x;
          const dy = asteroid.pos.y - bullet.pos.y;
          const dist = Math.sqrt(dx * dx + dy * dy);

          if (dist < asteroid.radius) {
            bullets.splice(j, 1);
            asteroids.splice(i, 1);
            setScore(s => s + 10);

            // Split asteroid if large enough
            if (asteroid.radius > 15) {
              const newRadius = asteroid.radius / 2;
              asteroids.push(createAsteroid(asteroid.pos.x, asteroid.pos.y, newRadius));
              asteroids.push(createAsteroid(asteroid.pos.x, asteroid.pos.y, newRadius));
            }

            // Spawn new asteroid if getting low
            if (asteroids.length < 3) {
              asteroids.push(createAsteroid());
            }
            break;
          }
        }

        // Check collision with ship
        if (gameStateRef.current.invulnerable <= 0) {
          const dx = asteroid.pos.x - ship.pos.x;
          const dy = asteroid.pos.y - ship.pos.y;
          const dist = Math.sqrt(dx * dx + dy * dy);

          if (dist < asteroid.radius + 10) {
            setGameOver(true);
          }
        }
      }

      if (gameStateRef.current.invulnerable > 0) {
        gameStateRef.current.invulnerable--;
      }

      // Draw asteroids
      ctx.strokeStyle = '#888';
      ctx.lineWidth = 2;
      asteroids.forEach(asteroid => {
        ctx.beginPath();
        asteroid.points.forEach((point, i) => {
          const x = asteroid.pos.x + point.x;
          const y = asteroid.pos.y + point.y;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        ctx.closePath();
        ctx.stroke();
      });

      // Draw bullets
      ctx.fillStyle = '#ff6b00';
      bullets.forEach(bullet => {
        ctx.beginPath();
        ctx.arc(bullet.pos.x, bullet.pos.y, 2, 0, Math.PI * 2);
        ctx.fill();
      });

      // Draw ship
      if (gameStateRef.current.invulnerable % 10 < 5 || gameStateRef.current.invulnerable === 0) {
        ctx.strokeStyle = '#ff6b00';
        ctx.lineWidth = 2;
        ctx.beginPath();

        const cos = Math.cos(ship.angle);
        const sin = Math.sin(ship.angle);

        // Ship nose
        ctx.moveTo(ship.pos.x + cos * 15, ship.pos.y + sin * 15);
        // Ship left
        ctx.lineTo(
          ship.pos.x + Math.cos(ship.angle + 2.5) * 10,
          ship.pos.y + Math.sin(ship.angle + 2.5) * 10
        );
        // Ship back
        ctx.lineTo(ship.pos.x - cos * 5, ship.pos.y - sin * 5);
        // Ship right
        ctx.lineTo(
          ship.pos.x + Math.cos(ship.angle - 2.5) * 10,
          ship.pos.y + Math.sin(ship.angle - 2.5) * 10
        );
        ctx.closePath();
        ctx.stroke();

        // Thrust flame
        if (keys['ArrowUp']) {
          ctx.beginPath();
          ctx.moveTo(ship.pos.x - cos * 5, ship.pos.y - sin * 5);
          ctx.lineTo(
            ship.pos.x - cos * 15 + Math.random() * 4 - 2,
            ship.pos.y - sin * 15 + Math.random() * 4 - 2
          );
          ctx.strokeStyle = '#ff6b00';
          ctx.stroke();
        }
      }

      animationFrame = requestAnimationFrame(gameLoop);
    };

    animationFrame = requestAnimationFrame(gameLoop);

    return () => {
      cancelAnimationFrame(animationFrame);
      window.removeEventListener('resize', resizeCanvas);
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('keyup', handleKeyUp);
      canvas.removeEventListener('pointerdown', handlePointerDown);
      canvas.removeEventListener('pointerup', handlePointerUp);
      canvas.removeEventListener('pointerleave', handlePointerUp);
    };
  }, [gameOver]);

  const handleRestart = () => {
    setGameOver(false);
    setScore(0);
  };

  return (
    <div className="relative w-full h-full bg-gradient-to-br from-gray-900/80 to-gray-800/80 backdrop-blur-xl rounded-3xl shadow-2xl border border-white/10 overflow-hidden">
      <canvas
        ref={canvasRef}
        className="w-full h-full"
        style={{ touchAction: 'none' }}
      />

      {/* Score overlay */}
      <div className="absolute top-4 left-4 right-4 flex justify-between items-center pointer-events-none">
        <div className="text-white text-sm font-bold bg-black/40 px-3 py-1 rounded-full">
          Score: {score}
        </div>
        <div className="text-gray-400 text-xs bg-black/40 px-3 py-1 rounded-full hidden sm:block">
          ← → rotate • ↑ thrust • space shoot
        </div>
        <div className="text-gray-400 text-xs bg-black/40 px-3 py-1 rounded-full sm:hidden">
          Tap to play
        </div>
      </div>

      {/* Game Over overlay */}
      {gameOver && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="text-center">
            <h3 className="text-2xl font-bold text-white mb-2">Game Over!</h3>
            <p className="text-gray-300 mb-4">Final Score: {score}</p>
            <button
              onClick={handleRestart}
              className="bg-orange-500 hover:bg-orange-600 text-white px-6 py-2 rounded-lg font-semibold transition-colors"
            >
              Play Again
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
