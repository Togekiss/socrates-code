import React from 'react';

export interface SegmentedOption<T> {
  value: T;
  label: React.ReactNode;
  count?: number;
  icon?: React.ReactNode;
  disabled?: boolean;
}

export interface SegmentedControlProps<T> {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (val: T) => void;
  ariaLabel?: string;
  className?: string;
}

export function SegmentedControl<T extends string | number>({
  options,
  value,
  onChange,
  ariaLabel,
  className = '',
}: SegmentedControlProps<T>) {
  const containerClasses = ['segmented-control', className].filter(Boolean).join(' ');

  return (
    <div className={containerClasses} role="tablist" aria-label={ariaLabel}>
      {options.map(option => {
        const isActive = option.value === value;
        const btnClasses = [
          'segmented-btn',
          isActive ? 'is-active' : '',
        ]
          .filter(Boolean)
          .join(' ');

        return (
          <button
            key={String(option.value)}
            type="button"
            role="tab"
            aria-selected={isActive}
            disabled={option.disabled}
            className={btnClasses}
            onClick={() => onChange(option.value)}
          >
            {option.icon}
            <span>{option.label}</span>
            {typeof option.count === 'number' && (
              <span className="segmented-count" style={{ opacity: 0.8, fontSize: '0.75rem' }}>
                ({option.count})
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
