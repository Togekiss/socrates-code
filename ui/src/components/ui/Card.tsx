import React from 'react';

export interface PanelSurfaceProps extends React.HTMLAttributes<HTMLDivElement> {
  children?: React.ReactNode;
  className?: string;
}

export const PanelSurface: React.FC<PanelSurfaceProps> = ({
  children,
  className = '',
  ...rest
}) => {
  return (
    <div className={['panel-surface', className].filter(Boolean).join(' ')} {...rest}>
      {children}
    </div>
  );
};

export type DataCardAccent = 'accent' | 'warning' | 'danger' | 'success' | 'resolved';

export interface DataCardProps extends React.HTMLAttributes<HTMLDivElement> {
  accent?: DataCardAccent;
  children?: React.ReactNode;
  className?: string;
}

export const DataCard: React.FC<DataCardProps> = ({
  accent,
  children,
  className = '',
  ...rest
}) => {
  const classNames = [
    'data-card',
    accent ? `data-card--${accent}` : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={classNames} {...rest}>
      {children}
    </div>
  );
};

export interface StatCardProps {
  label: React.ReactNode;
  value: React.ReactNode;
  icon?: React.ReactNode;
  subtext?: React.ReactNode;
  onClick?: () => void;
  className?: string;
}

export const StatCard: React.FC<StatCardProps> = ({
  label,
  value,
  icon,
  subtext,
  onClick,
  className = '',
}) => {
  const classNames = ['stat-card', className].filter(Boolean).join(' ');

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
    >
      <div className="stat-card-header">
        <span className="stat-card-label">{label}</span>
        {icon && <div className="stat-card-icon">{icon}</div>}
      </div>
      <div className="stat-card-value">{value}</div>
      {subtext && <div className="stat-card-subtext">{subtext}</div>}
    </div>
  );
};
