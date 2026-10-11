import React, { useEffect, useRef } from 'react';

/**
 * Midjourney-style 3D Generative ASCII Intelligence Sphere.
 * Renders a rotating 3D ellipsoid in pure ASCII characters at subtle opacity.
 */
export const AsciiSphere: React.FC<{ active?: boolean }> = ({ active = false }) => {
  const canvasRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    let animationFrameId: number;
    let A = 0;
    let B = 0;

    const chars = ' .,-~:;=!*#$@';
    const width = 64;
    const height = 26;

    const renderFrame = () => {
      A += active ? 0.045 : 0.015;
      B += active ? 0.035 : 0.012;

      const cosA = Math.cos(A), sinA = Math.sin(A);
      const cosB = Math.cos(B), sinB = Math.sin(B);

      const output: string[] = [];
      const zBuffer: number[] = new Array(width * height).fill(0);
      const bBuffer: string[] = new Array(width * height).fill(' ');

      // Generate points on an ellipsoid surface
      for (let theta = 0; theta < 6.28; theta += 0.12) {
        const cosT = Math.cos(theta), sinT = Math.sin(theta);

        for (let phi = 0; phi < 6.28; phi += 0.06) {
          const cosP = Math.cos(phi), sinP = Math.sin(phi);

          // 3D coordinates on sphere
          const x = cosP * cosT;
          const y = sinP;
          const z = cosP * sinT + 2.4;

          const ooz = 1 / z;

          // Projection to 2D screen
          const xp = Math.floor(width / 2 + 28 * ooz * (x * cosA - z * sinA));
          const yp = Math.floor(height / 2 + 13 * ooz * (x * sinA * sinB + y * cosB - z * cosA * sinB));

          // Normal luminance
          const L = cosP * cosT * sinB - cosA * cosT * sinP - sinA * sinT + cosB * (cosA * sinT - sinA * cosT * sinP);

          if (xp >= 0 && xp < width && yp >= 0 && yp < height) {
            const idx = xp + yp * width;
            if (ooz > zBuffer[idx]) {
              zBuffer[idx] = ooz;
              const charIdx = Math.max(0, Math.floor((L + 1) * 6));
              bBuffer[idx] = chars[Math.min(chars.length - 1, charIdx)];
            }
          }
        }
      }

      for (let j = 0; j < height; j++) {
        output.push(bBuffer.slice(j * width, (j + 1) * width).join(''));
      }

      if (canvasRef.current) {
        canvasRef.current.textContent = output.join('\n');
      }

      animationFrameId = requestAnimationFrame(renderFrame);
    };

    animationFrameId = requestAnimationFrame(renderFrame);

    return () => {
      cancelAnimationFrame(animationFrameId);
    };
  }, [active]);

  return (
    <pre
      ref={canvasRef}
      className="ascii-canvas-background"
      aria-hidden="true"
    />
  );
};
