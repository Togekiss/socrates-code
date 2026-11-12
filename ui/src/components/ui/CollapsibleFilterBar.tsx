import React, { useState, useRef, useLayoutEffect, useMemo } from 'react';
import { Filter, ChevronDown, RotateCcw } from 'lucide-react';
import { Badge } from './Badge';

export interface CollapsibleFilterBarProps {
  title?: string;
  activeCount?: number;
  summaryPills?: React.ReactNode;
  onClearAll?: () => void;
  defaultCollapsed?: boolean;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

const extractPills = (node: React.ReactNode): React.ReactNode[] => {
  if (!node) return [];
  if (React.isValidElement(node) && (node.props as { children?: React.ReactNode })?.children) {
    return React.Children.toArray((node.props as { children?: React.ReactNode }).children).filter(Boolean);
  }
  return React.Children.toArray(node).filter(Boolean);
};

interface CollapsibleFilterSummaryProps {
  summaryPills: React.ReactNode;
}

const CollapsibleFilterSummary: React.FC<CollapsibleFilterSummaryProps> = ({ summaryPills }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const measureRef = useRef<HTMLDivElement>(null);
  const moreRef = useRef<HTMLDivElement>(null);
  const pills = useMemo(() => extractPills(summaryPills), [summaryPills]);
  const [visibleCount, setVisibleCount] = useState<number>(pills.length);

  useLayoutEffect(() => {
    const container = containerRef.current;
    const measure = measureRef.current;
    if (!container || !measure || pills.length === 0) {
      setVisibleCount(pills.length);
      return;
    }

    const updateVisible = () => {
      const availableWidth = container.clientWidth;
      if (availableWidth <= 0) return;

      const children = Array.from(measure.children) as HTMLElement[];
      const moreBadge = moreRef.current;
      const moreWidth = moreBadge ? moreBadge.offsetWidth : 28;
      const pillGap = 6; // 0.35rem

      let usedWidth = 0;
      let count = 0;

      for (let i = 0; i < pills.length; i++) {
        const itemEl = children[i];
        const itemWidth = itemEl ? itemEl.offsetWidth : 60;
        const widthWithItem = usedWidth + (count > 0 ? pillGap : 0) + itemWidth;

        // If this is the last pill, check if it fits without "..."
        if (i === pills.length - 1) {
          if (widthWithItem <= availableWidth) {
            count++;
          }
          break;
        }

        // For intermediate pills, check if item + "..." badge fits
        if (widthWithItem + pillGap + moreWidth <= availableWidth) {
          usedWidth = widthWithItem;
          count++;
        } else {
          break;
        }
      }

      setVisibleCount(count);
    };

    updateVisible();

    const resizeObserver = new ResizeObserver(() => {
      updateVisible();
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
    };
  }, [pills]);

  if (pills.length === 0) return null;

  const hiddenCount = pills.length - visibleCount;

  return (
    <div
      ref={containerRef}
      className="collapsible-filter-summary"
      onClick={e => e.stopPropagation()}
    >
      {pills.slice(0, visibleCount)}
      {hiddenCount > 0 && visibleCount > 0 && (
        <Badge
          variant="neutral"
          title={`${hiddenCount} more active filter${hiddenCount > 1 ? 's' : ''}`}
        >
          ...
        </Badge>
      )}

      {/* Off-screen measurement container */}
      <div
        ref={measureRef}
        aria-hidden="true"
        style={{
          position: 'fixed',
          top: -9999,
          left: -9999,
          visibility: 'hidden',
          display: 'flex',
          gap: '0.35rem',
          pointerEvents: 'none',
          whiteSpace: 'nowrap',
        }}
      >
        {pills.map((pill, idx) => (
          <div key={idx} style={{ display: 'inline-flex' }}>
            {pill}
          </div>
        ))}
        <div ref={moreRef} style={{ display: 'inline-flex' }}>
          <Badge variant="neutral">...</Badge>
        </div>
      </div>
    </div>
  );
};

export const CollapsibleFilterBar: React.FC<CollapsibleFilterBarProps> = ({
  title = 'Filters',
  activeCount = 0,
  summaryPills,
  onClearAll,
  defaultCollapsed = false,
  actions,
  children,
  className = '',
}) => {
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed);

  const containerClasses = [
    'collapsible-filter-container',
    isCollapsed ? 'is-collapsed' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <div className={containerClasses}>
      <div
        className="collapsible-filter-header"
        onClick={() => setIsCollapsed(prev => !prev)}
      >
        <div className="collapsible-filter-title">
          <Filter size={16} color="var(--accent-secondary)" />
          <span>{title}</span>
          {activeCount > 0 && (
            <Badge variant="accent">
              {activeCount} filter{activeCount > 1 ? 's' : ''}
            </Badge>
          )}
        </div>

        {summaryPills && (
          <CollapsibleFilterSummary summaryPills={summaryPills} />
        )}

        <div
          className="collapsible-filter-actions"
          onClick={e => e.stopPropagation()}
        >
          {onClearAll && activeCount > 0 && (
            <button
              type="button"
              className="collapsible-filter-reset"
              onClick={onClearAll}
              title="Reset all filters"
            >
              <RotateCcw size={12} />
              <span>Reset</span>
            </button>
          )}

          {actions}

          <button
            type="button"
            className="collapsible-filter-toggle"
            onClick={() => setIsCollapsed(prev => !prev)}
            aria-label={isCollapsed ? 'Expand filters' : 'Collapse filters'}
          >
            <span>{isCollapsed ? 'Show' : 'Hide'}</span>
            <ChevronDown
              size={14}
              style={{
                transform: isCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
                transition: 'transform var(--transition-fast)',
              }}
            />
          </button>
        </div>
      </div>

      <div className="collapsible-filter-body">{children}</div>
    </div>
  );
};
