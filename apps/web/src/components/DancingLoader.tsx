import { useState } from 'react';

const DANCES = Array.from(
  { length: 16 },
  (_, index) => `/loading/dance-${String(index + 1).padStart(2, '0')}.gif`,
);

function pickDance(): string {
  return DANCES[Math.floor(Math.random() * DANCES.length)];
}

interface DancingLoaderProps {
  label?: string;
  overlay?: boolean;
  compact?: boolean;
}

export function DancingLoader({ label, overlay = false, compact = false }: DancingLoaderProps) {
  // Pick one animation per mount; a new loading session gets a new dancer.
  const [src] = useState(pickDance);
  return (
    <div
      className={`dancing-loader${overlay ? ' dancing-loader--overlay' : ''}${compact ? ' dancing-loader--compact' : ''}`}
      role="status"
      aria-live="polite"
    >
      <img src={src} alt="" aria-hidden="true" draggable={false} />
      {label ? <span className="dancing-loader__label">{label}</span> : null}
    </div>
  );
}

interface DancingSpinnerProps {
  size?: number;
  className?: string;
}

/**
 * Tiny inline dancer for buttons and inline status rows.
 * It replaces the old circular CSS spinners: same footprint, but animated.
 */
export function DancingSpinner({ size = 22, className }: DancingSpinnerProps) {
  const [src] = useState(pickDance);
  return (
    <img
      src={src}
      alt=""
      aria-hidden="true"
      draggable={false}
      className={`dancing-spinner${className ? ` ${className}` : ''}`}
      style={{ width: size, height: size }}
    />
  );
}
