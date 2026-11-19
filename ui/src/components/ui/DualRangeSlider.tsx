import React, { useRef, useState } from 'react';

export interface DualRangeSliderProps {
  min: number;
  max: number;
  value: [number, number];
  onChange: (value: [number, number]) => void;
  step?: number;
  disabled?: boolean;
  minAriaLabel?: string;
  maxAriaLabel?: string;
  className?: string;
}

/**
 * Accessible dual-thumb range slider built from two overlapping native range inputs.
 */
export const DualRangeSlider: React.FC<DualRangeSliderProps> = ({
  min,
  max,
  value,
  onChange,
  step = 1,
  disabled = false,
  minAriaLabel = 'Minimum value',
  maxAriaLabel = 'Maximum value',
  className = '',
}) => {
  const sliderRef = useRef<HTMLDivElement>(null);
  const [lastActive, setLastActive] = useState<'min' | 'max'>('max');

  const safeMax = Math.max(min, max);
  const isDisabled = disabled || safeMax <= min;
  const low = Math.max(min, Math.min(value[0], safeMax));
  const high = Math.max(low, Math.min(value[1], safeMax));

  const span = safeMax - min;
  const minPercent = span > 0 ? ((low - min) / span) * 100 : 0;
  const maxPercent = span > 0 ? ((high - min) / span) * 100 : 100;

  // Keep the outward-movable thumb on top whenever both thumbs meet at an endpoint.
  let minZIndex = lastActive === 'min' ? 4 : 3;
  let maxZIndex = lastActive === 'max' ? 4 : 3;
  if (low >= safeMax) {
    minZIndex = 4;
    maxZIndex = 3;
  } else if (high <= min) {
    minZIndex = 3;
    maxZIndex = 4;
  }

  const handleTrackPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (isDisabled || e.target instanceof HTMLInputElement) return;
    const container = sliderRef.current;
    if (!container || span <= 0) return;

    const rect = container.getBoundingClientRect();
    const thumbRadius = 8;
    const usableWidth = Math.max(1, rect.width - thumbRadius * 2);
    const ratio = Math.max(0, Math.min(1, (e.clientX - (rect.left + thumbRadius)) / usableWidth));
    const raw = min + ratio * span;
    const snapped = Math.max(min, Math.min(safeMax, Math.round(raw / step) * step));

    const distToLow = Math.abs(snapped - low);
    const distToHigh = Math.abs(snapped - high);

    if (distToLow < distToHigh || (distToLow === distToHigh && snapped < low)) {
      setLastActive('min');
      onChange([Math.min(snapped, high), high]);
    } else {
      setLastActive('max');
      onChange([low, Math.max(snapped, low)]);
    }
  };

  const containerClasses = [
    'dual-range-slider',
    isDisabled ? 'is-disabled' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div
      ref={sliderRef}
      className={containerClasses}
      onPointerDown={handleTrackPointerDown}
    >
      <div className="dual-range-track" />
      <div className="dual-range-fill-bounds">
        <div
          className="dual-range-fill"
          style={{
            left: `${minPercent}%`,
            width: `${Math.max(0, maxPercent - minPercent)}%`,
          }}
        />
      </div>

      <input
        type="range"
        min={min}
        max={safeMax}
        step={step}
        value={low}
        disabled={isDisabled}
        aria-label={minAriaLabel}
        className="dual-range-input"
        style={{ zIndex: minZIndex }}
        onPointerDown={() => setLastActive('min')}
        onFocus={() => setLastActive('min')}
        onChange={e => {
          const nextLow = Math.min(Number(e.target.value), high);
          setLastActive('min');
          onChange([nextLow, high]);
        }}
      />

      <input
        type="range"
        min={min}
        max={safeMax}
        step={step}
        value={high}
        disabled={isDisabled}
        aria-label={maxAriaLabel}
        className="dual-range-input"
        style={{ zIndex: maxZIndex }}
        onPointerDown={() => setLastActive('max')}
        onFocus={() => setLastActive('max')}
        onChange={e => {
          const nextHigh = Math.max(Number(e.target.value), low);
          setLastActive('max');
          onChange([low, nextHigh]);
        }}
      />
    </div>
  );
};
