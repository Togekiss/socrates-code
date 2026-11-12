import React from 'react';
import { Loader2 } from 'lucide-react';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'success' | 'warning';
export type ButtonSize = 'md' | 'sm' | 'xs' | 'icon';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: React.ReactNode;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = 'secondary',
      size = 'md',
      loading = false,
      icon,
      disabled,
      className = '',
      children,
      ...rest
    },
    ref
  ) => {
    const classNames = [
      'btn',
      variant ? `btn-${variant}` : '',
      size && size !== 'md' ? `btn-${size}` : '',
      loading ? 'is-loading' : '',
      className,
    ]
      .filter(Boolean)
      .join(' ');

    const spinnerSize = size === 'xs' ? 12 : 14;

    return (
      <button
        ref={ref}
        type={rest.type || 'button'}
        className={classNames}
        disabled={disabled || loading}
        {...rest}
      >
        {loading ? (
          <Loader2 size={spinnerSize} className="animate-spin" />
        ) : (
          icon && <span className="btn-icon-wrapper">{icon}</span>
        )}
        {children}
      </button>
    );
  }
);

Button.displayName = 'Button';
