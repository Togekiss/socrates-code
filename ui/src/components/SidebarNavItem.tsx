import React from 'react';
import { Loader2 } from 'lucide-react';
import type { TabType } from './Sidebar';

export interface NavItemConfig {
  id: TabType;
  label: string;
  icon: React.ComponentType<{ size?: number; className?: string; style?: React.CSSProperties }>;
  badge?: number | string | null;
  badgeColor?: string;
  isPulsing?: boolean;
}

interface SidebarNavItemProps {
  item: NavItemConfig;
  isActive: boolean;
  isDisabled: boolean;
  collapsed: boolean;
  onSelect: (id: TabType) => void;
}

export const SidebarNavItem: React.FC<SidebarNavItemProps> = ({
  item,
  isActive,
  isDisabled,
  collapsed,
  onSelect,
}) => {
  const Icon = item.icon;

  return (
    <button
      onClick={() => onSelect(item.id)}
      disabled={isDisabled}
      title={collapsed ? item.label : undefined}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: collapsed ? 'center' : 'space-between',
        gap: '0.65rem',
        width: '100%',
        padding: collapsed ? '0.6rem' : '0.55rem 0.75rem',
        borderRadius: '8px',
        border: isActive
          ? '1px solid var(--border-highlight)'
          : '1px solid transparent',
        background: isActive
          ? 'var(--bg-tertiary)'
          : 'transparent',
        color: isActive
          ? 'var(--text-primary)'
          : isDisabled
          ? 'var(--text-muted)'
          : 'var(--text-secondary)',
        cursor: isDisabled ? 'not-allowed' : 'pointer',
        opacity: isDisabled ? 0.45 : 1,
        fontWeight: isActive ? 600 : 500,
        fontSize: '0.875rem',
        textAlign: 'left',
        transition: 'all var(--transition-fast)',
        position: 'relative',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', minWidth: 0 }}>
        <Icon
          size={18}
          style={{
            color: isActive ? 'var(--accent-secondary)' : 'inherit',
            flexShrink: 0,
          }}
        />
        {!collapsed && (
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {item.label}
          </span>
        )}
      </div>

      {!collapsed && item.badge && (
        <span
          style={{
            fontSize: '0.7rem',
            padding: '0.15rem 0.45rem',
            borderRadius: '10px',
            background: item.badgeColor || 'var(--accent-primary)',
            color: '#fff',
            fontWeight: 700,
            flexShrink: 0,
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.25rem',
          }}
        >
          {item.isPulsing && (
            <Loader2 size={10} className="animate-spin" />
          )}
          {item.badge}
        </span>
      )}

      {collapsed && item.badge && (
        <span
          style={{
            position: 'absolute',
            top: '4px',
            right: '4px',
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            background: item.badgeColor || 'var(--accent-primary)',
          }}
        />
      )}
    </button>
  );
};
