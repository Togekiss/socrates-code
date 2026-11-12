import { useState, useEffect } from 'react';

/**
 * Socrates Design System — Responsive Text Dictionary & Utilities
 * 
 * Centralized registry of viewport-adaptive copy.
 * Strings defined here adapt between standard (desktop) and compact (mobile)
 * viewports via the <ResponsiveText /> component or useResponsiveText() hook.
 */

export interface ResponsiveTextEntry {
  desktop: string;
  mobile: string;
}

export const RESPONSIVE_TEXT = {
  sortOldest: {
    desktop: 'Oldest First',
    mobile: 'Oldest',
  },
  sortNewest: {
    desktop: 'Newest First',
    mobile: 'Newest',
  },
  newCharacterGroup: {
    desktop: 'New Character Group',
    mobile: 'New Group',
  },
  editGroup: {
    desktop: 'Edit Group',
    mobile: 'Edit',
  },
} as const satisfies Record<string, ResponsiveTextEntry>;

export type ResponsiveTextKey = keyof typeof RESPONSIVE_TEXT;

/**
 * Hook for string-only contexts (such as `placeholder`, `title`, or `aria-label`)
 * where a React JSX component cannot be used directly.
 */
export function useResponsiveText() {
  const [isMobile, setIsMobile] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia('(max-width: 768px)').matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mq = window.matchMedia('(max-width: 768px)');
    const onChange = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  const t = (key: ResponsiveTextKey): string => {
    return isMobile ? RESPONSIVE_TEXT[key].mobile : RESPONSIVE_TEXT[key].desktop;
  };

  return { isMobile, t };
}

