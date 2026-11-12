import React from 'react';
import { X } from 'lucide-react';

export type BadgeVariant = 'accent' | 'success' | 'warning' | 'danger' | 'info' | 'neutral';

export interface BadgeProps {
  variant?: BadgeVariant;
  children: React.ReactNode;
  className?: string;
  title?: string;
}

export const Badge: React.FC<BadgeProps> = ({
  variant = 'neutral',
  children,
  className = '',
  title,
}) => {
  const classNames = ['badge', `badge-${variant}`, className].filter(Boolean).join(' ');

  return (
    <span className={classNames} title={title}>
      {children}
    </span>
  );
};

export interface FilterChipProps {
  active?: boolean;
  variant?: BadgeVariant;
  icon?: React.ReactNode;
  onClick?: () => void;
  onRemove?: () => void;
  children: React.ReactNode;
  className?: string;
  title?: string;
}

export const FilterChip: React.FC<FilterChipProps> = ({
  active = false,
  variant = 'accent',
  icon,
  onClick,
  onRemove,
  children,
  className = '',
  title,
}) => {
  const classNames = [
    'chip',
    active ? 'chip-active' : '',
    active && variant !== 'accent' ? `chip-active-${variant}` : '',
    !onClick ? 'chip-static' : '',
    onRemove ? 'chip-removable' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (onClick && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      onClick();
    }
  };

  return (
    <div
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      className={classNames}
      onClick={onClick}
      onKeyDown={handleKeyDown}
      title={title}
    >
      {icon && <span className="chip-icon">{icon}</span>}
      <span className="chip-label">{children}</span>
      {onRemove && (
        <button
          type="button"
          className="chip-remove-btn"
          aria-label="Remove filter"
          onClick={e => {
            e.stopPropagation();
            onRemove();
          }}
        >
          <X size={12} />
        </button>
      )}
    </div>
  );
};
