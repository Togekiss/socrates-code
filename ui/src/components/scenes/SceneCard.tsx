import React, { useState } from 'react';
import { ExternalLink, ChevronDown, ChevronRight } from 'lucide-react';

interface SceneCardProps {
  scene: any;
  allCharacters: any[];
  charactersFilter: number[];
  setCharactersFilter: (filter: number[]) => void;
}

export const SceneCard: React.FC<SceneCardProps> = ({ scene, allCharacters, charactersFilter, setCharactersFilter }) => {
  const [expanded, setExpanded] = useState(false);

  const getCharName = (id: number) => {
    const main = allCharacters.find(c => c.id === id);
    if (main) return main.names[0];
    for (const c of allCharacters) {
      if (c.other_versions) {
        const nested = c.other_versions.find((v: any) => v.id === id);
        if (nested) return nested.names[0];
      }
    }
    return null;
  };

  const startExcerpt = scene.start?.content || scene.start?.excerpt || scene.start_excerpt || '';
  const endExcerpt = scene.end?.content || scene.end?.excerpt || scene.end_excerpt || '';
  const hasStartExcerpt = Boolean(startExcerpt && startExcerpt.trim());
  const hasEndExcerpt = Boolean(endExcerpt && endExcerpt.trim());

  const formatTimestamp = (ts?: string) => {
    if (!ts) return null;
    try {
      const d = new Date(ts);
      return isNaN(d.getTime()) ? null : d.toLocaleString();
    } catch {
      return null;
    }
  };

  return (
    <div style={{ 
      background: 'var(--bg-tertiary)', 
      borderRadius: '4px', 
      overflow: 'hidden', 
      border: '1px solid var(--border-color)', 
      display: 'flex', 
      flexDirection: 'column' 
    }}>
      <div style={{ padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'baseline' }}>
            <strong>{scene.category} &gt; {scene.channel}</strong> {scene.type === 'thread' && <span style={{ opacity: 0.7 }}>| {scene.thread_name || 'Thread'}</span>}
            <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
              {formatTimestamp(scene.start?.timestamp) || 'N/A'}
            </div>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <span style={{ padding: '0.2rem 0.5rem', background: 'rgba(255,255,255,0.1)', borderRadius: '4px', fontSize: '0.8rem' }}>{scene.status}</span>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
              {scene.end && scene.start ? (scene.end.index - scene.start.index + 1) : 0} msgs
            </span>
          </div>
        </div>
        
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.25rem' }}>
          {(scene.characters || []).map((cid: number) => {
            const name = getCharName(cid);
            const isKnown = !!name;
            return (
              <button 
                key={cid} 
                onClick={() => {
                  if (isKnown && !charactersFilter.includes(cid)) {
                    setCharactersFilter([...charactersFilter, cid]);
                  }
                }}
                disabled={!isKnown}
                style={{ 
                  padding: '0.1rem 0.4rem', 
                  background: 'rgba(255,255,255,0.05)', 
                  border: '1px solid var(--border-color)', 
                  borderRadius: '12px', 
                  fontSize: '0.75rem',
                  color: isKnown ? 'var(--text-primary)' : 'var(--text-secondary)',
                  cursor: isKnown ? 'pointer' : 'default',
                  opacity: isKnown ? 1 : 0.5
                }}
              >
                {name || `Unknown (${cid})`}
              </button>
            );
          })}
        </div>
        
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap', marginTop: '0.25rem' }}>
          {scene.start?.link ? (
            <a
              href={scene.start.link}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.3rem',
                padding: '0.25rem 0.6rem',
                fontSize: '0.8rem',
                background: 'rgba(139, 92, 246, 0.2)',
                border: '1px solid #8b5cf6',
                color: '#c4b5fd',
                borderRadius: '6px',
                textDecoration: 'none',
                fontWeight: 600,
              }}
            >
              <ExternalLink size={12} /> Open first message in Discord
            </a>
          ) : (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.3rem',
                padding: '0.25rem 0.6rem',
                fontSize: '0.8rem',
                background: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid var(--border-color)',
                color: 'var(--text-secondary)',
                borderRadius: '6px',
                opacity: 0.5,
                cursor: 'not-allowed',
                fontWeight: 600,
              }}
            >
              <ExternalLink size={12} /> Open first message in Discord
            </span>
          )}
          
          {scene.end?.link ? (
            <a
              href={scene.end.link}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.3rem',
                padding: '0.25rem 0.6rem',
                fontSize: '0.8rem',
                background: 'rgba(139, 92, 246, 0.2)',
                border: '1px solid #8b5cf6',
                color: '#c4b5fd',
                borderRadius: '6px',
                textDecoration: 'none',
                fontWeight: 600,
              }}
            >
              <ExternalLink size={12} /> Open last message in Discord
            </a>
          ) : (
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.3rem',
                padding: '0.25rem 0.6rem',
                fontSize: '0.8rem',
                background: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid var(--border-color)',
                color: 'var(--text-secondary)',
                borderRadius: '6px',
                opacity: 0.5,
                cursor: 'not-allowed',
                fontWeight: 600,
              }}
            >
              <ExternalLink size={12} /> Open last message in Discord
            </span>
          )}
        </div>
      </div>

      {/* Message Excerpts Section */}
      <div style={{ borderTop: '1px solid var(--border-color)' }}>
        <button 
          type="button"
          onClick={() => setExpanded(!expanded)}
          style={{ 
            width: '100%', 
            background: 'rgba(0,0,0,0.2)', 
            border: 'none', 
            padding: '0.5rem 1rem', 
            display: 'flex', 
            alignItems: 'center', 
            gap: '0.5rem', 
            color: 'var(--text-secondary)', 
            fontSize: '0.85rem', 
            textAlign: 'left', 
            cursor: 'pointer' 
          }}
        >
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          Message Previews
        </button>
        
        {expanded && (
          <div style={{ padding: '0.75rem 1rem', background: 'rgba(0,0,0,0.1)', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <strong style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                  First Message:
                </strong>
                {scene.start?.timestamp && (
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    {formatTimestamp(scene.start.timestamp)}
                  </span>
                )}
              </div>
              <div
                style={{
                  fontSize: '0.8rem',
                  color: 'var(--text-secondary)',
                  fontStyle: 'italic',
                  background: 'rgba(0, 0, 0, 0.25)',
                  padding: '0.5rem 0.75rem',
                  borderRadius: '6px',
                  lineHeight: '1.4',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }}
              >
                {hasStartExcerpt ? startExcerpt : <span style={{ opacity: 0.5, fontStyle: 'normal' }}>No start message excerpt available.</span>}
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <strong style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                  Last Message:
                </strong>
                {scene.end?.timestamp && (
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    {formatTimestamp(scene.end.timestamp)}
                  </span>
                )}
              </div>
              <div
                style={{
                  fontSize: '0.8rem',
                  color: 'var(--text-secondary)',
                  fontStyle: 'italic',
                  background: 'rgba(0, 0, 0, 0.25)',
                  padding: '0.5rem 0.75rem',
                  borderRadius: '6px',
                  lineHeight: '1.4',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }}
              >
                {hasEndExcerpt ? endExcerpt : <span style={{ opacity: 0.5, fontStyle: 'normal' }}>No end message excerpt available.</span>}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
