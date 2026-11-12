import { useState } from 'react';
import { Sparkles, ChevronDown } from 'lucide-react';
import { PanelSurface } from './ui';

export const AiDisclosure = () => {
  const [collapsed, setCollapsed] = useState(true);

  return (
    <PanelSurface style={{ margin: '2rem auto', maxWidth: '750px', width: '100%' }}>
      <div
        onClick={() => setCollapsed(prev => !prev)}
        role="button"
        tabIndex={0}
        aria-expanded={!collapsed}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setCollapsed(prev => !prev);
          }
        }}
        className="flex-row items-center justify-between"
        style={{ cursor: 'pointer', userSelect: 'none' }}
      >
        <div className="flex-row items-center gap-sm">
          <Sparkles size={20} style={{ color: 'var(--accent-secondary)', flexShrink: 0 }} />
          <span style={{ fontSize: '1.15rem', fontWeight: 600, color: 'var(--text-primary)' }}>
            AI usage disclosure
          </span>
        </div>
        <div className="flex-row items-center gap-xs" style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
          <span>{collapsed ? 'Show' : 'Hide'}</span>
          <ChevronDown
            size={16}
            style={{
              transform: collapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
              transition: 'transform var(--transition-fast)',
            }}
          />
        </div>
      </div>

      {!collapsed && (
        <div
          className="flex-col gap-sm"
          style={{
            marginTop: '1rem',
            paddingTop: '1rem',
            borderTop: '1px solid var(--border-color)',
            fontSize: '0.9rem',
            lineHeight: 1.6,
            color: 'var(--text-secondary)',
          }}
        >
          <div>
            <strong style={{ color: 'var(--text-primary)' }}>
              No AI agent, LLM or GenAI is reading Discord messages.
            </strong>
          </div>
          <div>
            An AI agent was used to help implement features and keep documentation updated,{' '}
            <span style={{ color: 'var(--text-primary)' }}>
              but it only sees the code, not the content of the backup itself.{' '}
            </span>
            All it sees from the database are numbers like the ones above.
          </div>
          <div>
            The core logic of this tool like scene detection and fix suggestions are clever{' '}
            <span style={{ color: 'var(--text-primary)' }}>pattern recognition formulas</span>.{' '}
            Cold hard math I wrote by hand back when LLMs were dumber than my cat (and he&apos;s very dumb)
          </div>
        </div>
      )}
    </PanelSurface>
  );
};
