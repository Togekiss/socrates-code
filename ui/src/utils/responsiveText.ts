import { useState, useEffect } from 'react';

/**
 * Socrates Design System — Responsive Text Dictionary & Utilities
 * 
 * Centralized registry of viewport-adaptive copy.
 * Strings defined here adapt between standard (desktop), reduced (tablet) and compact (mobile)
 * viewports via the <ResponsiveText /> component or useResponsiveText() hook.
 */

export interface ResponsiveTextEntry {
  desktop: string;
  tablet: string;
  mobile: string;
}

export const RESPONSIVE_TEXT = {
  sortOldest: {
    desktop: 'Oldest First',
    tablet: 'Oldest',
    mobile: 'Oldest',
  },
  sortNewest: {
    desktop: 'Newest First',
    tablet: 'Newest',
    mobile: 'Newest',
  },
  newCharacterGroup: {
    desktop: 'New Character Group',
    tablet: 'New Group',
    mobile: 'Group',
  },
  editGroup: {
    desktop: 'Edit Group',
    tablet: 'Edit',
    mobile: 'Edit',
  },
  acceptDiscordLink: {
    desktop: 'Accept Link',
    tablet: 'Accept Link',
    mobile: 'Link',
  },
  descCharacters: {
    desktop: 'Browse character rosters, manage aliases, nest alternate versions, and assign writers.',
    tablet: 'Manage character rosters, versions, and writer assignments.',
    mobile: 'Manage characters, versions, and writers.',
  },
  descWriters: {
    desktop: 'Manage writer profiles, Discord user ID links, and character assignments.',
    tablet: 'Manage writer profiles, Discord links, and characters.',
    mobile: 'Manage writers and Discord links.',
  },
  descScenes: {
    desktop: 'Browse roleplay scenes across channels and threads with character, writer, and date filters.',
    tablet: 'Browse roleplay scenes with character, writer, and date filters.',
    mobile: 'Browse roleplay scenes.',
  },
  descChatSessions: {
    desktop: 'Browse continuous chatroom roleplay sessions grouped by activity and participants.',
    tablet: 'Browse chatroom roleplay sessions and participants.',
    mobile: 'Browse chatroom sessions.',
  },
  descEvents: {
    desktop: 'Explore multi-channel story events, character movements, and timeline spans.',
    tablet: 'Explore multi-channel events and character movements.',
    mobile: 'Explore story events.',
  },
  descSceneIssues: {
    desktop: 'Review and resolve uncertain automatic scene splits and soft boundaries.',
    tablet: 'Review automatic scene splits and soft boundaries.',
    mobile: 'Review scene boundary issues.',
  },
  descFlaggedMessages: {
    desktop: 'Triage failed tupper messages and out-of-character boundaries detected during parsing.',
    tablet: 'Triage failed tuppers and OOC boundary messages.',
    mobile: 'Triage flagged messages.',
  },
} as const satisfies Record<string, ResponsiveTextEntry>;

export type ResponsiveTextKey = keyof typeof RESPONSIVE_TEXT;

/**
 * Hook for string-only contexts (such as `placeholder`, `title`, or `aria-label`)
 * where a React JSX component cannot be used directly.
 */
export function useResponsiveText() {

  const [isTablet, setIsTablet] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia('(max-width: 768px)').matches;
  });

  const [isMobile, setIsMobile] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia('(max-width: 480px)').matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined') return;

    const mqt = window.matchMedia('(max-width: 768px)');
    const onChangeTablet = (e: MediaQueryListEvent) => setIsTablet(e.matches);
    const mqm = window.matchMedia('(max-width: 480px)');
    const onChangeMobile = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    
    mqt.addEventListener('change', onChangeTablet);
    mqm.addEventListener('change', onChangeMobile);
    return () => {mqt.removeEventListener('change', onChangeTablet); mqm.removeEventListener('change', onChangeMobile);}
  }, []);

  const t = (key: ResponsiveTextKey): string => {
    return isMobile ? RESPONSIVE_TEXT[key].mobile : isTablet ? RESPONSIVE_TEXT[key].tablet : RESPONSIVE_TEXT[key].desktop;
  };

  return { isMobile, t };
}

