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
  rotation: number;
  rotationSpeed: number;
  type: 'normal' | 'fast' | 'heavy';
  health: number;
}

interface Bullet {
  pos: Vector;
  vel: Vector;
  life: number;
  type: 'normal' | 'laser' | 'spread';
}

interface Particle {
  pos: Vector;
  vel: Vector;
  life: number;
  maxLife: number;
  color: string;
  size: number;
}

interface PowerUp {
  pos: Vector;
  vel: Vector;
  type: 'shield' | 'rapidfire' | 'tripleshot' | 'laser';
  rotation: number;
}

interface Trail {
  pos: Vector;
  life: number;
}

export function MiniAsteroids() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [score, setScore] = useState(0);
  const [highScore, setHighScore] = useState(() => {
    return parseInt(localStorage.getItem('asteroidsHighScore') || '0');
  });
  const [gameOver, setGameOver] = useState(false);
  const [combo, setCombo] = useState(0);
  const [showCombo, setShowCombo] = useState(false);
  const [gameFocused, setGameFocused] = useState(false);

  const gameStateRef = useRef({
    ship: {
      pos: { x: 0, y: 0 },
      vel: { x: 0, y: 0 },
      angle: 0,
      shield: 0,
      rapidFire: 0,
      tripleShot: 0,
      laser: 0,
    },
    asteroids: [] as Asteroid[],
    bullets: [] as Bullet[],
    particles: [] as Particle[],
    powerUps: [] as PowerUp[],
    trail: [] as Trail[],
    keys: {} as Record<string, boolean>,
    lastTime: 0,
    invulnerable: 0,
    shootCooldown: 0,
    lastHitTime: 0,
    comboCount: 0,
    shake: 0,
    difficulty: 1,
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

    // Create particles
    const createParticles = (x: number, y: number, color: string, count = 20) => {
      for (let i = 0; i < count; i++) {
        const angle = Math.random() * Math.PI * 2;
        const speed = 50 + Math.random() * 150;
        gameStateRef.current.particles.push({
          pos: { x, y },
          vel: {
            x: Math.cos(angle) * speed,
            y: Math.sin(angle) * speed,
          },
          life: 30 + Math.random() * 30,
          maxLife: 60,
          color,
          size: 2 + Math.random() * 3,
        });
      }
    };

    // Generate random asteroid with types
    const createAsteroid = (x?: number, y?: number, radius = 30): Asteroid => {
      const types: ('normal' | 'fast' | 'heavy')[] = ['normal', 'normal', 'fast', 'heavy'];
      const type = types[Math.floor(Math.random() * types.length)];

      const pos = x !== undefined && y !== undefined
        ? { x, y }
        : {
            x: Math.random() * canvas.width,
            y: Math.random() * canvas.height,
          };

      const angle = Math.random() * Math.PI * 2;
      let speed = (40 + Math.random() * 40) * gameStateRef.current.difficulty; // Faster base speed
      let health = 1;

      // Type modifiers
      if (type === 'fast') {
        speed *= 2.0; // Even faster
        radius *= 0.75;
      } else if (type === 'heavy') {
        speed *= 0.5;
        radius *= 1.4;
        health = 2;
      }

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

      return {
        pos,
        vel,
        radius,
        points,
        rotation: 0,
        rotationSpeed: (Math.random() - 0.5) * 3, // Faster rotation for more dynamic feel
        type,
        health,
      };
    };

    // Create power-up
    const spawnPowerUp = (x: number, y: number) => {
      if (Math.random() < 0.3) { // 30% chance to spawn
        const types: ('shield' | 'rapidfire' | 'tripleshot' | 'laser')[] =
          ['shield', 'rapidfire', 'tripleshot', 'laser'];
        const type = types[Math.floor(Math.random() * types.length)];

        gameStateRef.current.powerUps.push({
          pos: { x, y },
          vel: { x: (Math.random() - 0.5) * 50, y: (Math.random() - 0.5) * 50 },
          type,
          rotation: 0,
        });
      }
    };

    // Initialize asteroids
    const initGame = () => {
      gameStateRef.current.asteroids = [];
      for (let i = 0; i < 4; i++) {
        gameStateRef.current.asteroids.push(createAsteroid());
      }
      gameStateRef.current.bullets = [];
      gameStateRef.current.particles = [];
      gameStateRef.current.powerUps = [];
      gameStateRef.current.trail = [];
      gameStateRef.current.ship.vel = { x: 0, y: 0 };
      gameStateRef.current.ship.angle = 0;
      gameStateRef.current.ship.shield = 0;
      gameStateRef.current.ship.rapidFire = 0;
      gameStateRef.current.ship.tripleShot = 0;
      gameStateRef.current.ship.laser = 0;
      gameStateRef.current.invulnerable = 120;
      gameStateRef.current.comboCount = 0;
      gameStateRef.current.difficulty = 1;
      setScore(0);
      setCombo(0);
      setGameOver(false);
    };
    initGame();

    // Keyboard controls
    const handleKeyDown = (e: KeyboardEvent) => {
      // Check if we're typing in an input field
      const activeElement = document.activeElement;
      const isTyping = activeElement instanceof HTMLInputElement ||
                       activeElement instanceof HTMLTextAreaElement ||
                       activeElement instanceof HTMLSelectElement ||
                       (activeElement?.getAttribute('contenteditable') === 'true');

      // Only capture keys if game is focused and not typing in a form
      if (!gameFocused || isTyping) return;

      const key = e.key.toLowerCase();
      gameStateRef.current.keys[e.key] = true;
      gameStateRef.current.keys[key] = true;

      if (e.key === ' ' || e.key === 'ArrowUp' || e.key === 'ArrowLeft' || e.key === 'ArrowRight' ||
          key === 'w' || key === 'a' || key === 's' || key === 'd') {
        e.preventDefault();
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      // Check if we're typing in an input field
      const activeElement = document.activeElement;
      const isTyping = activeElement instanceof HTMLInputElement ||
                       activeElement instanceof HTMLTextAreaElement ||
                       activeElement instanceof HTMLSelectElement ||
                       (activeElement?.getAttribute('contenteditable') === 'true');

      // Only capture keys if game is focused and not typing in a form
      if (!gameFocused || isTyping) return;

      const key = e.key.toLowerCase();
      gameStateRef.current.keys[e.key] = false;
      gameStateRef.current.keys[key] = false;
    };

    // Handle canvas click to activate game focus
    const handleCanvasClick = (e: MouseEvent) => {
      e.stopPropagation();
      setGameFocused(true);
    };

    // Handle document click to deactivate game focus when clicking outside
    const handleDocumentClick = (e: MouseEvent) => {
      if (!canvas.contains(e.target as Node)) {
        setGameFocused(false);
        // Clear all keys when losing focus
        gameStateRef.current.keys = {};
      }
    };

    // Touch/Mouse controls for mobile
    const handlePointerDown = (e: PointerEvent) => {
      e.preventDefault();
      setGameFocused(true);

      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      const third = canvas.width / 3;
      if (x < third) {
        gameStateRef.current.keys['ArrowLeft'] = true;
        gameStateRef.current.keys['a'] = true;
      } else if (x > third * 2) {
        gameStateRef.current.keys['ArrowRight'] = true;
        gameStateRef.current.keys['d'] = true;
      } else {
        gameStateRef.current.keys['ArrowUp'] = true;
        gameStateRef.current.keys['w'] = true;
        gameStateRef.current.keys[' '] = true;
      }
    };

    const handlePointerUp = () => {
      gameStateRef.current.keys = {};
    };

    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('keyup', handleKeyUp);
    document.addEventListener('click', handleDocumentClick);
    canvas.addEventListener('click', handleCanvasClick);
    canvas.addEventListener('pointerdown', handlePointerDown);
    canvas.addEventListener('pointerup', handlePointerUp);
    canvas.addEventListener('pointerleave', handlePointerUp);

    // Game loop
    let animationFrame: number;
    const gameLoop = (timestamp: number) => {
      const dt = gameStateRef.current.lastTime ? (timestamp - gameStateRef.current.lastTime) / 1000 : 0;
      gameStateRef.current.lastTime = timestamp;

      if (!ctx || gameOver) return;

      const { ship, asteroids, bullets, particles, powerUps, trail, keys } = gameStateRef.current;

      // Apply screen shake
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      if (gameStateRef.current.shake > 0) {
        const shakeX = (Math.random() - 0.5) * gameStateRef.current.shake;
        const shakeY = (Math.random() - 0.5) * gameStateRef.current.shake;
        ctx.translate(shakeX, shakeY);
        gameStateRef.current.shake *= 0.9;
      }

      // Clear canvas with smooth fade effect for motion trails
      ctx.fillStyle = 'rgba(10, 10, 15, 0.2)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      // Update difficulty
      gameStateRef.current.difficulty = 1 + Math.floor(score / 100) * 0.1;

      // Decrease power-up timers
      if (ship.rapidFire > 0) ship.rapidFire--;
      if (ship.tripleShot > 0) ship.tripleShot--;
      if (ship.laser > 0) ship.laser--;
      if (ship.shield > 0) ship.shield--;

      // Update ship - smooth rotation (Arrow keys or WASD)
      const rotationSpeed = 0.07; // Very slow, precise turning
      if (keys['ArrowLeft'] || keys['a']) ship.angle -= rotationSpeed * dt * 60;
      if (keys['ArrowRight'] || keys['d']) ship.angle += rotationSpeed * dt * 60;

      if (keys['ArrowUp'] || keys['w']) {
        const thrust = 350; // More powerful thrust
        ship.vel.x += Math.cos(ship.angle) * thrust * dt;
        ship.vel.y += Math.sin(ship.angle) * thrust * dt;

        // Thrust particles
        if (Math.random() < 0.6) {
          particles.push({
            pos: {
              x: ship.pos.x - Math.cos(ship.angle) * 10,
              y: ship.pos.y - Math.sin(ship.angle) * 10,
            },
            vel: {
              x: -Math.cos(ship.angle) * 120 + (Math.random() - 0.5) * 60,
              y: -Math.sin(ship.angle) * 120 + (Math.random() - 0.5) * 60,
            },
            life: 25,
            maxLife: 25,
            color: '#ff6b00',
            size: 2.5,
          });
        }
      }

      // Smooth friction
      ship.vel.x *= 0.985;
      ship.vel.y *= 0.985;

      // Max speed cap for smooth movement
      const maxSpeed = 400;
      const speed = Math.sqrt(ship.vel.x * ship.vel.x + ship.vel.y * ship.vel.y);
      if (speed > maxSpeed) {
        ship.vel.x = (ship.vel.x / speed) * maxSpeed;
        ship.vel.y = (ship.vel.y / speed) * maxSpeed;
      }

      // Add smooth trail
      if (Math.random() < 0.4) {
        trail.push({
          pos: { ...ship.pos },
          life: 30,
        });
      }

      // Update ship position
      ship.pos.x += ship.vel.x * dt;
      ship.pos.y += ship.vel.y * dt;

      // Wrap around screen
      if (ship.pos.x < 0) ship.pos.x = canvas.width;
      if (ship.pos.x > canvas.width) ship.pos.x = 0;
      if (ship.pos.y < 0) ship.pos.y = canvas.height;
      if (ship.pos.y > canvas.height) ship.pos.y = 0;

      // Shoot
      if (gameStateRef.current.shootCooldown > 0) {
        gameStateRef.current.shootCooldown--;
      }

      const cooldownRate = ship.rapidFire > 0 ? 3 : 12;

      if (keys[' '] && gameStateRef.current.shootCooldown <= 0) {
        const bulletSpeed = 600; // Much faster bullets

        if (ship.laser > 0) {
          // Laser beam - super fast
          bullets.push({
            pos: { ...ship.pos },
            vel: {
              x: Math.cos(ship.angle) * bulletSpeed * 1.8,
              y: Math.sin(ship.angle) * bulletSpeed * 1.8,
            },
            life: 35,
            type: 'laser',
          });
        } else if (ship.tripleShot > 0) {
          // Triple shot
          for (let i = -1; i <= 1; i++) {
            const angle = ship.angle + i * 0.15;
            bullets.push({
              pos: { ...ship.pos },
              vel: {
                x: Math.cos(angle) * bulletSpeed,
                y: Math.sin(angle) * bulletSpeed,
              },
              life: 60,
              type: 'spread',
            });
          }
        } else {
          // Normal shot
          bullets.push({
            pos: { ...ship.pos },
            vel: {
              x: Math.cos(ship.angle) * bulletSpeed,
              y: Math.sin(ship.angle) * bulletSpeed,
            },
            life: 60,
            type: 'normal',
          });
        }

        gameStateRef.current.shootCooldown = cooldownRate;
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

      // Update particles with smooth physics
      for (let i = particles.length - 1; i >= 0; i--) {
        const particle = particles[i];
        particle.pos.x += particle.vel.x * dt;
        particle.pos.y += particle.vel.y * dt;
        particle.vel.x *= 0.96; // Smoother decay
        particle.vel.y *= 0.96;
        particle.life--;

        if (particle.life <= 0) {
          particles.splice(i, 1);
        }
      }

      // Update trail
      for (let i = trail.length - 1; i >= 0; i--) {
        trail[i].life--;
        if (trail[i].life <= 0) {
          trail.splice(i, 1);
        }
      }

      // Update power-ups
      for (let i = powerUps.length - 1; i >= 0; i--) {
        const powerUp = powerUps[i];
        powerUp.pos.x += powerUp.vel.x * dt;
        powerUp.pos.y += powerUp.vel.y * dt;
        powerUp.rotation += dt * 3;

        // Wrap around
        if (powerUp.pos.x < -20) powerUp.pos.x = canvas.width + 20;
        if (powerUp.pos.x > canvas.width + 20) powerUp.pos.x = -20;
        if (powerUp.pos.y < -20) powerUp.pos.y = canvas.height + 20;
        if (powerUp.pos.y > canvas.height + 20) powerUp.pos.y = -20;

        // Check collision with ship
        const dx = powerUp.pos.x - ship.pos.x;
        const dy = powerUp.pos.y - ship.pos.y;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist < 20) {
          // Activate power-up
          switch (powerUp.type) {
            case 'shield':
              ship.shield = 600; // 10 seconds
              break;
            case 'rapidfire':
              ship.rapidFire = 600;
              break;
            case 'tripleshot':
              ship.tripleShot = 600;
              break;
            case 'laser':
              ship.laser = 600;
              break;
          }
          createParticles(powerUp.pos.x, powerUp.pos.y, '#00ff88', 15);
          powerUps.splice(i, 1);
        }
      }

      // Update asteroids
      for (let i = asteroids.length - 1; i >= 0; i--) {
        const asteroid = asteroids[i];
        asteroid.pos.x += asteroid.vel.x * dt;
        asteroid.pos.y += asteroid.vel.y * dt;
        asteroid.rotation += asteroid.rotationSpeed * dt;

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

            asteroid.health--;

            if (asteroid.health <= 0) {
              // Asteroid destroyed
              asteroids.splice(i, 1);

              // Update combo
              const now = timestamp;
              if (now - gameStateRef.current.lastHitTime < 2000) {
                gameStateRef.current.comboCount++;
              } else {
                gameStateRef.current.comboCount = 1;
              }
              gameStateRef.current.lastHitTime = now;

              const comboMultiplier = Math.min(gameStateRef.current.comboCount, 10);
              const points = 10 * comboMultiplier;

              setScore(s => {
                const newScore = s + points;
                if (newScore > highScore) {
                  setHighScore(newScore);
                  localStorage.setItem('asteroidsHighScore', newScore.toString());
                }
                return newScore;
              });

              setCombo(comboMultiplier);
              setShowCombo(true);
              setTimeout(() => setShowCombo(false), 1000);

              // Explosion particles
              const color = asteroid.type === 'fast' ? '#ff6b00' :
                           asteroid.type === 'heavy' ? '#ff0066' : '#888888';
              createParticles(asteroid.pos.x, asteroid.pos.y, color, 30);

              gameStateRef.current.shake = 8;

              // Split asteroid if large enough
              if (asteroid.radius > 15) {
                const newRadius = asteroid.radius / 2;
                asteroids.push(createAsteroid(asteroid.pos.x, asteroid.pos.y, newRadius));
                asteroids.push(createAsteroid(asteroid.pos.x, asteroid.pos.y, newRadius));
              } else {
                // Chance to spawn power-up
                spawnPowerUp(asteroid.pos.x, asteroid.pos.y);
              }

              // Spawn new asteroid if getting low
              if (asteroids.length < 2) {
                asteroids.push(createAsteroid());
              }
            } else {
              // Hit but not destroyed - create small effect
              createParticles(bullet.pos.x, bullet.pos.y, '#ffaa00', 8);
              gameStateRef.current.shake = 3;
            }

            break;
          }
        }

        // Check collision with ship
        if (gameStateRef.current.invulnerable <= 0 && ship.shield <= 0) {
          const dx = asteroid.pos.x - ship.pos.x;
          const dy = asteroid.pos.y - ship.pos.y;
          const dist = Math.sqrt(dx * dx + dy * dy);

          if (dist < asteroid.radius + 10) {
            createParticles(ship.pos.x, ship.pos.y, '#ff0000', 40);
            gameStateRef.current.shake = 20;
            setGameOver(true);
          }
        } else if (ship.shield > 0) {
          // Shield collision - smooth bounce with physics
          const dx = asteroid.pos.x - ship.pos.x;
          const dy = asteroid.pos.y - ship.pos.y;
          const dist = Math.sqrt(dx * dx + dy * dy);

          if (dist < asteroid.radius + 25) {
            const angle = Math.atan2(dy, dx);
            const bounceForce = 200;
            // Maintain some of the asteroid's momentum for smoother bounce
            asteroid.vel.x = Math.cos(angle) * bounceForce + asteroid.vel.x * 0.3;
            asteroid.vel.y = Math.sin(angle) * bounceForce + asteroid.vel.y * 0.3;
            createParticles(asteroid.pos.x, asteroid.pos.y, '#00ffff', 12);
            gameStateRef.current.shake = 4;
          }
        }
      }

      if (gameStateRef.current.invulnerable > 0) {
        gameStateRef.current.invulnerable--;
      }

      // Draw smooth trail with gradient fade
      trail.forEach(t => {
        const alpha = t.life / 30;
        ctx.globalAlpha = alpha * 0.5;
        ctx.fillStyle = '#ff6b00';
        ctx.beginPath();
        ctx.arc(t.pos.x, t.pos.y, 2, 0, Math.PI * 2);
        ctx.fill();
      });
      ctx.globalAlpha = 1;

      // Draw asteroids with glow
      asteroids.forEach(asteroid => {
        const color = asteroid.type === 'fast' ? '#ff6b00' :
                     asteroid.type === 'heavy' ? '#ff0066' : '#888888';

        ctx.save();
        ctx.translate(asteroid.pos.x, asteroid.pos.y);
        ctx.rotate(asteroid.rotation);

        // Glow effect
        if (asteroid.type !== 'normal') {
          ctx.shadowBlur = 15;
          ctx.shadowColor = color;
        }

        ctx.strokeStyle = color;
        ctx.lineWidth = asteroid.type === 'heavy' ? 3 : 2;
        ctx.beginPath();
        asteroid.points.forEach((point, i) => {
          if (i === 0) ctx.moveTo(point.x, point.y);
          else ctx.lineTo(point.x, point.y);
        });
        ctx.closePath();
        ctx.stroke();

        // Health indicator for heavy asteroids
        if (asteroid.type === 'heavy' && asteroid.health > 1) {
          ctx.shadowBlur = 0;
          ctx.fillStyle = '#ff0066';
          ctx.font = 'bold 12px monospace';
          ctx.textAlign = 'center';
          ctx.fillText(asteroid.health.toString(), 0, 5);
        }

        ctx.restore();
      });

      // Draw particles with fade
      particles.forEach(particle => {
        const alpha = particle.life / particle.maxLife;
        ctx.globalAlpha = alpha;
        ctx.fillStyle = particle.color;
        ctx.beginPath();
        ctx.arc(particle.pos.x, particle.pos.y, particle.size, 0, Math.PI * 2);
        ctx.fill();
      });
      ctx.globalAlpha = 1;

      // Draw bullets with enhanced glow and trails
      bullets.forEach(bullet => {
        const lifeRatio = bullet.life / 60;

        if (bullet.type === 'laser') {
          // Laser with trail
          ctx.shadowBlur = 25;
          ctx.shadowColor = '#00ffff';
          ctx.globalAlpha = 0.8 + lifeRatio * 0.2;
          ctx.fillStyle = '#00ffff';
          ctx.beginPath();
          ctx.arc(bullet.pos.x, bullet.pos.y, 5, 0, Math.PI * 2);
          ctx.fill();

          // Laser trail
          ctx.globalAlpha = 0.3;
          ctx.fillStyle = '#00ffff';
          ctx.beginPath();
          ctx.arc(bullet.pos.x - bullet.vel.x * dt * 2, bullet.pos.y - bullet.vel.y * dt * 2, 3, 0, Math.PI * 2);
          ctx.fill();
        } else if (bullet.type === 'spread') {
          ctx.shadowBlur = 12;
          ctx.shadowColor = '#ffaa00';
          ctx.globalAlpha = 0.9 + lifeRatio * 0.1;
          ctx.fillStyle = '#ffaa00';
          ctx.beginPath();
          ctx.arc(bullet.pos.x, bullet.pos.y, 3, 0, Math.PI * 2);
          ctx.fill();
        } else {
          ctx.shadowBlur = 15;
          ctx.shadowColor = '#ff6b00';
          ctx.globalAlpha = 1;
          ctx.fillStyle = '#ff6b00';
          ctx.beginPath();
          ctx.arc(bullet.pos.x, bullet.pos.y, 2.5, 0, Math.PI * 2);
          ctx.fill();

          // Bullet trail
          ctx.globalAlpha = 0.4;
          ctx.beginPath();
          ctx.arc(bullet.pos.x - bullet.vel.x * dt, bullet.pos.y - bullet.vel.y * dt, 1.5, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.globalAlpha = 1;
        ctx.shadowBlur = 0;
      });

      // Draw power-ups with pulsing glow
      powerUps.forEach(powerUp => {
        ctx.save();
        ctx.translate(powerUp.pos.x, powerUp.pos.y);
        ctx.rotate(powerUp.rotation);

        const color = powerUp.type === 'shield' ? '#00ffff' :
                     powerUp.type === 'rapidfire' ? '#ffaa00' :
                     powerUp.type === 'tripleshot' ? '#ff00ff' : '#00ff88';

        // Pulsing effect
        const pulse = Math.sin(timestamp * 0.005) * 0.3 + 1;
        ctx.shadowBlur = 20 * pulse;
        ctx.shadowColor = color;
        ctx.strokeStyle = color;
        ctx.lineWidth = 2.5;

        // Draw icon based on type
        ctx.beginPath();
        if (powerUp.type === 'shield') {
          // Shield icon
          ctx.arc(0, 0, 10, 0, Math.PI * 2);
        } else if (powerUp.type === 'rapidfire') {
          // Rapid fire icon
          ctx.moveTo(-8, -8);
          ctx.lineTo(8, 0);
          ctx.lineTo(-8, 8);
        } else if (powerUp.type === 'tripleshot') {
          // Triple shot icon
          ctx.moveTo(0, -10);
          ctx.lineTo(0, 10);
          ctx.moveTo(-6, -8);
          ctx.lineTo(-6, 8);
          ctx.moveTo(6, -8);
          ctx.lineTo(6, 8);
        } else {
          // Laser icon
          ctx.moveTo(-10, 0);
          ctx.lineTo(10, 0);
          ctx.moveTo(-8, -4);
          ctx.lineTo(8, -4);
          ctx.moveTo(-8, 4);
          ctx.lineTo(8, 4);
        }
        ctx.stroke();
        ctx.restore();
      });

      // Draw ship with shield
      if (gameStateRef.current.invulnerable % 10 < 5 || gameStateRef.current.invulnerable === 0) {
        // Shield visual with pulsing animation
        if (ship.shield > 0) {
          const shieldPulse = Math.sin(timestamp * 0.008) * 0.15 + 0.85;
          const shieldRadius = 25 + Math.sin(timestamp * 0.01) * 2;

          ctx.strokeStyle = '#00ffff';
          ctx.lineWidth = 3;
          ctx.shadowBlur = 25 * shieldPulse;
          ctx.shadowColor = '#00ffff';
          ctx.globalAlpha = 0.5 + shieldPulse * 0.2;
          ctx.beginPath();
          ctx.arc(ship.pos.x, ship.pos.y, shieldRadius, 0, Math.PI * 2);
          ctx.stroke();

          // Inner shield glow
          ctx.globalAlpha = 0.2;
          ctx.fillStyle = '#00ffff';
          ctx.fill();

          ctx.globalAlpha = 1;
          ctx.shadowBlur = 0;
        }

        ctx.strokeStyle = '#ff6b00';
        ctx.lineWidth = 2;
        ctx.shadowBlur = 15;
        ctx.shadowColor = '#ff6b00';
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
        ctx.shadowBlur = 0;

        // Enhanced thrust flame with smooth animation
        if (keys['ArrowUp'] || keys['w']) {
          const flameLength = 18 + Math.random() * 8;
          const flameWidth = 4 + Math.random() * 2;

          ctx.shadowBlur = 25;
          ctx.shadowColor = '#ff6b00';

          // Main flame
          ctx.strokeStyle = '#ff6b00';
          ctx.lineWidth = 4;
          ctx.lineCap = 'round';
          ctx.beginPath();
          ctx.moveTo(ship.pos.x - cos * 5, ship.pos.y - sin * 5);
          ctx.lineTo(
            ship.pos.x - cos * flameLength + (Math.random() - 0.5) * flameWidth,
            ship.pos.y - sin * flameLength + (Math.random() - 0.5) * flameWidth
          );
          ctx.stroke();

          // Inner glow
          ctx.strokeStyle = '#ffaa00';
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.moveTo(ship.pos.x - cos * 5, ship.pos.y - sin * 5);
          ctx.lineTo(
            ship.pos.x - cos * (flameLength * 0.6),
            ship.pos.y - sin * (flameLength * 0.6)
          );
          ctx.stroke();

          ctx.shadowBlur = 0;
          ctx.lineCap = 'butt';
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
      document.removeEventListener('click', handleDocumentClick);
      canvas.removeEventListener('click', handleCanvasClick);
      canvas.removeEventListener('pointerdown', handlePointerDown);
      canvas.removeEventListener('pointerup', handlePointerUp);
      canvas.removeEventListener('pointerleave', handlePointerUp);
    };
  }, [gameOver, highScore, gameFocused]);

  const handleRestart = () => {
    setGameOver(false);
    setScore(0);
    setCombo(0);
  };

  const getPowerUpIcon = (type: string) => {
    switch (type) {
      case 'shield': return '🛡️';
      case 'rapidfire': return '⚡';
      case 'tripleshot': return '✨';
      case 'laser': return '🔥';
      default: return '';
    }
  };

  const activePowerUps = [];
  const ship = gameStateRef.current.ship;
  if (ship.shield > 0) activePowerUps.push({ type: 'shield', time: ship.shield });
  if (ship.rapidFire > 0) activePowerUps.push({ type: 'rapidfire', time: ship.rapidFire });
  if (ship.tripleShot > 0) activePowerUps.push({ type: 'tripleshot', time: ship.tripleShot });
  if (ship.laser > 0) activePowerUps.push({ type: 'laser', time: ship.laser });

  return (
    <div className={`relative w-full h-full bg-gradient-to-br from-gray-900/80 to-gray-800/80 backdrop-blur-xl rounded-3xl shadow-2xl overflow-hidden transition-all duration-300 ${
      gameFocused
        ? 'border-2 border-orange-500/70 ring-2 ring-orange-500/30'
        : 'border border-white/10'
    }`}>
      <canvas
        ref={canvasRef}
        className="w-full h-full cursor-pointer"
        style={{ touchAction: 'none' }}
      />

      {/* Score overlay */}
      <div className="absolute top-4 left-4 right-4 flex justify-between items-start pointer-events-none">
        <div className="flex flex-col gap-2">
          <div className="text-white text-lg font-bold bg-black/60 px-4 py-2 rounded-full backdrop-blur-sm border border-white/20">
            Score: <span className="text-orange-400">{score}</span>
          </div>
          <div className="text-gray-300 text-sm bg-black/60 px-4 py-2 rounded-full backdrop-blur-sm border border-white/20">
            High: <span className="text-yellow-400">{highScore}</span>
          </div>
          {showCombo && combo > 1 && (
            <div className="text-orange-400 text-xl font-bold bg-black/80 px-4 py-2 rounded-full backdrop-blur-sm border-2 border-orange-400 animate-pulse">
              {combo}x COMBO! 🔥
            </div>
          )}
        </div>

        <div className="flex flex-col gap-2">
          {activePowerUps.map((powerUp, i) => (
            <div key={i} className="text-sm bg-black/60 px-3 py-2 rounded-full backdrop-blur-sm border border-white/20 flex items-center gap-2">
              <span>{getPowerUpIcon(powerUp.type)}</span>
              <span className="text-white">{Math.ceil(powerUp.time / 60)}s</span>
            </div>
          ))}
        </div>
      </div>

      {/* Controls hint */}
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 pointer-events-none">
        {!gameFocused && !gameOver && (
          <div className="text-orange-400 text-sm font-semibold bg-black/70 px-5 py-2.5 rounded-full border-2 border-orange-500/50 animate-pulse mb-2">
            Click to play
          </div>
        )}
        <div className="text-gray-400 text-xs bg-black/40 px-4 py-2 rounded-full hidden sm:block">
          A/D or ← → rotate • W or ↑ thrust • space shoot
        </div>
        <div className="text-gray-400 text-xs bg-black/40 px-4 py-2 rounded-full sm:hidden">
          Left: turn left • Right: turn right • Center: thrust & shoot
        </div>
      </div>

      {/* Game Over overlay */}
      {gameOver && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/70 backdrop-blur-md">
          <div className="text-center bg-gray-900/90 p-8 rounded-2xl border-2 border-orange-500/50 shadow-2xl">
            <h3 className="text-4xl font-bold text-white mb-3 drop-shadow-lg">Game Over!</h3>
            <div className="mb-2">
              <p className="text-gray-300 text-lg">Final Score</p>
              <p className="text-5xl font-bold text-orange-400 mb-4">{score}</p>
            </div>
            {score === highScore && score > 0 && (
              <p className="text-yellow-400 text-sm mb-4 font-semibold">🏆 NEW HIGH SCORE! 🏆</p>
            )}
            <button
              onClick={handleRestart}
              className="bg-gradient-to-r from-orange-500 to-orange-600 hover:from-orange-600 hover:to-orange-700 text-white px-8 py-3 rounded-xl font-bold transition-all transform hover:scale-105 shadow-lg text-lg"
            >
              Play Again
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
