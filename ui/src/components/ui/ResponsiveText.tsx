import React from 'react';
import { RESPONSIVE_TEXT, type ResponsiveTextKey } from '../../utils';

export interface ResponsiveTextProps {
  /**
   * Pre-registered key from `RESPONSIVE_TEXT`.
   */
  textKey?: ResponsiveTextKey;
  /**
   * Fallback or custom desktop label if not using a dictionary key.
   */
  desktop?: string;
  /**
   * Fallback or custom mobile label if not using a dictionary key.
   */
  mobile?: string;
  className?: string;
}

/**
 * Pure CSS-driven responsive text component.
 * Renders both desktop and mobile variants into the DOM and toggles them via CSS media query,
 * ensuring zero resize re-renders and no initial render layout shift.
 */
export const ResponsiveText: React.FC<ResponsiveTextProps> = ({
  textKey,
  desktop,
  mobile,
  className = '',
}) => {
  const d = textKey ? RESPONSIVE_TEXT[textKey].desktop : desktop;
  const m = textKey ? RESPONSIVE_TEXT[textKey].mobile : mobile;

  return (
    <span className={`responsive-text-wrapper ${className}`.trim()}>
      <span className="responsive-text-desktop">{d}</span>
      <span className="responsive-text-mobile">{m}</span>
    </span>
  );
};
