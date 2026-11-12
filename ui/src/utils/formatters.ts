/**
 * Safe date parsing and formatting utilities.
 */

/**
 * Formats an ISO or standard timestamp string into a localized date & time string.
 * Returns null if the timestamp is missing, empty, or invalid.
 */
export function formatTimestamp(ts?: string | null): string | null {
  if (!ts) return null;
  try {
    const d = new Date(ts);
    return isNaN(d.getTime()) ? null : d.toLocaleString();
  } catch {
    return null;
  }
}

/**
 * Formats an ISO or standard timestamp string into a localized short date string.
 * Returns null if the timestamp is missing, empty, or invalid.
 */
export function formatShortDate(ts?: string | null): string | null {
  if (!ts) return null;
  try {
    const d = new Date(ts);
    return isNaN(d.getTime()) ? null : d.toLocaleDateString();
  } catch {
    return null;
  }
}

export interface DurationInfo {
  hours: number;
  label: string;
  tooltip: string;
}

/**
 * Calculates duration between start and end timestamps, unifying math across
 * SessionCard, EventCard, and other timeline components.
 * Returns null if either timestamp is missing, invalid, or end precedes start.
 */
export function getDurationInfo(start?: string | null, end?: string | null): DurationInfo | null {
  if (!start || !end) return null;
  try {
    const startTime = new Date(start).getTime();
    const endTime = new Date(end).getTime();
    if (isNaN(startTime) || isNaN(endTime) || endTime < startTime) return null;

    const diffMs = endTime - startTime;
    const totalHours = diffMs / (1000 * 60 * 60);
    const totalMinutes = Math.round(diffMs / (1000 * 60));

    if (diffMs === 0) {
      return {
        hours: 0,
        label: '0 hours',
        tooltip: 'Duration: 0 minutes',
      };
    }

    if (totalHours < 0.05) {
      return {
        hours: totalHours,
        label: '< 0.1 hours',
        tooltip: `Duration: ${totalMinutes} minute${totalMinutes === 1 ? '' : 's'}`,
      };
    }

    if (totalHours >= 48) {
      const days = (totalHours / 24).toFixed(1).replace(/\.0$/, '');
      return {
        hours: totalHours,
        label: `${days} days`,
        tooltip: `Duration: ${totalHours.toFixed(1)} hours (${totalMinutes} minutes)`,
      };
    }

    const formatted = totalHours.toFixed(1).replace(/\.0$/, '');
    const unit = formatted === '1' ? 'hour' : 'hours';
    return {
      hours: totalHours,
      label: `${formatted} ${unit}`,
      tooltip: `Duration: ${totalHours.toFixed(2)} hours (${totalMinutes} minute${totalMinutes === 1 ? '' : 's'})`,
    };
  } catch {
    return null;
  }
}
