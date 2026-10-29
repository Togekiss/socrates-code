import { useState } from 'react';
import { Sparkles, ChevronDown } from 'lucide-react';

export const AiDisclosure = () => {
  const [collapsed, setCollapsed] = useState(true);

  return (
    <div
      className="glass-panel"
      style={{
        background: 'var(--bg-secondary)',
        margin: '2rem auto',
        width: 'clamp(320px, 60%, 750px)',
        boxShadow: 'var(--glass-shadow)',
        transition: 'all var(--transition-fast)',
      }}
    >
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
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'pointer',
          userSelect: 'none',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <Sparkles size={22} style={{ color: 'var(--accent-secondary)', flexShrink: 0 }} />
          <span style={{ fontSize: '1.25rem', fontWeight: 600, color: 'var(--text-primary)' }}>
            AI usage disclosure
          </span>
        </div>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.35rem',
            color: 'var(--text-muted)',
            fontSize: '0.85rem',
          }}
        >
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
          style={{
            marginTop: '1rem',
            paddingTop: '1rem',
            borderTop: '1px solid var(--border-color)',
            display: 'flex',
            flexDirection: 'column',
            gap: '0.65rem',
            fontSize: '0.925rem',
            lineHeight: '1.6',
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
            Cold hard math I wrote by hand back when LLMs were dumber than my cat (he's very dumb)
          </div>
        </div>
      )}
    </div>
  );
};

