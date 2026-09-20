import React from 'react';
import { ExternalLink } from 'lucide-react';

interface SceneCardProps {
  scene: any;
  allCharacters: any[];
  charactersFilter: number[];
  setCharactersFilter: (filter: number[]) => void;
}

export const SceneCard: React.FC<SceneCardProps> = ({ scene, allCharacters, charactersFilter, setCharactersFilter }) => {
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

  return (
    <div style={{ background: 'var(--bg-tertiary)', padding: '1rem', borderRadius: '4px', border: '1px solid var(--border-color)', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
        <div>
          <strong>{scene.category} &gt; {scene.channel}</strong> {scene.type === 'thread' && <span style={{ opacity: 0.7 }}>| {scene.thread_name || 'Thread'}</span>}
          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{new Date(scene.start?.timestamp).toLocaleString()}</div>
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
      
      <div style={{ display: 'flex', gap: '1rem', fontSize: '0.85rem' }}>
        {scene.start?.link ? (
          <a href={scene.start.link} target="_blank" rel="noreferrer" style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', color: 'var(--accent-primary)', textDecoration: 'none' }}>
            Start <ExternalLink size={12} />
          </a>
        ) : <span style={{ color: 'var(--text-secondary)' }}>Start</span>}
        
        {scene.end?.link ? (
          <a href={scene.end.link} target="_blank" rel="noreferrer" style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', color: 'var(--accent-primary)', textDecoration: 'none' }}>
            End <ExternalLink size={12} />
          </a>
        ) : <span style={{ color: 'var(--text-secondary)', opacity: 0.5, pointerEvents: 'none' }}>End</span>}
      </div>
    </div>
  );
};
