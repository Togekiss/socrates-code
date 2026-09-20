import React, { useState } from 'react';
import { Edit2, ChevronDown, ChevronRight, Hash, User, Link as LinkIcon } from 'lucide-react';

interface CharacterCardProps {
  character: any;
  onEdit: (char: any, parent?: any) => void;
  onAddTagFilter: (tag: string) => void;
  isNested?: boolean;
  disableAccordion?: boolean;
}

export const CharacterCard: React.FC<CharacterCardProps> = ({ character, onEdit, onAddTagFilter, isNested = false, disableAccordion = false }) => {
  const [expanded, setExpanded] = useState(false);

  const mainName = character.names?.[0] || 'Unknown';
  const otherNames = character.names?.slice(1).join(', ');
  
  const mainWriter = character.writer?.[0] || 'Unknown';
  const otherWriters = character.writer?.slice(1).join(', ');

  const hasVersions = character.other_versions && character.other_versions.length > 0;
  
  const nestedType = isNested 
    ? (character.tags?.find((t: string) => ['familiar', 'npc', 'alter_ego', 'different_writer'].includes(t)) || 'other version')
    : null;

  return (
    <div style={{ 
      background: isNested ? 'var(--bg-tertiary)' : 'var(--bg-tertiary)', 
      borderRadius: isNested ? '4px' : '8px', 
      overflow: 'hidden', 
      border: isNested ? 'none' : '1px solid var(--border-color)',
      borderLeft: isNested ? '3px solid var(--accent-primary)' : '1px solid var(--border-color)'
    }}>
      
      <div style={{ padding: isNested ? '0.75rem' : '1rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        
        {/* Header Row */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: isNested ? '1rem' : '1.2rem', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              {mainName}
              {isNested && <span style={{ fontSize: '0.7rem', textTransform: 'uppercase', color: 'var(--accent-secondary)', background: 'rgba(255,255,255,0.1)', padding: '0.1rem 0.3rem', borderRadius: '4px' }}>{nestedType?.replace('_', ' ')}</span>}
            </h3>
            {otherNames && <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>aka {otherNames}</div>}
            
            {/* Flattened Parent Badge */}
            {character._parent && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.75rem', color: 'var(--accent-secondary)', marginTop: '0.25rem' }}>
                <LinkIcon size={10} /> Alt version of {character._parent.names?.[0]} (ID: {character._parent.id})
              </div>
            )}
            
            <div style={{ fontSize: '0.75rem', opacity: 0.5, marginTop: '0.25rem' }}>ID: {character.id}</div>
          </div>
          <button 
            onClick={() => onEdit(character, character._parent)}
            style={{ padding: '0.25rem 0.5rem', display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.85rem', background: 'transparent', border: '1px solid var(--border-color)', color: 'var(--text-secondary)', cursor: 'pointer', borderRadius: '4px' }}
          >
            <Edit2 size={14} /> Edit
          </button>
        </div>

        {/* Writer Row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
          <User size={14} /> 
          <span>{mainWriter}</span>
          {otherWriters && <span style={{ opacity: 0.6 }}>(aka {otherWriters})</span>}
        </div>

        {/* Tags Row */}
        {character.tags && character.tags.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.25rem', marginTop: '0.25rem' }}>
            {character.tags.map((tag: string) => (
              <button 
                key={tag} 
                onClick={() => onAddTagFilter(tag)}
                style={{ background: 'var(--bg-secondary)', border: 'none', padding: '0.1rem 0.5rem', borderRadius: '12px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.25rem', cursor: 'pointer', color: 'var(--accent-secondary)' }}
              >
                <Hash size={10} /> {tag.replace(/_/g, ' ')}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Other Versions Section */}
      {hasVersions && !isNested && !disableAccordion && (
        <div style={{ borderTop: '1px solid var(--border-color)' }}>
          <button 
            onClick={() => setExpanded(!expanded)}
            style={{ width: '100%', background: 'rgba(0,0,0,0.2)', border: 'none', padding: '0.5rem 1rem', display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.85rem', textAlign: 'left', cursor: 'pointer' }}
          >
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            Other Versions ({character.other_versions.length})
          </button>
          
          {expanded && (
            <div style={{ padding: '0.75rem 1rem', background: 'rgba(0,0,0,0.1)', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              {character.other_versions.map((v: any) => (
                <CharacterCard 
                  key={v.id} 
                  character={v} 
                  onEdit={(childChar) => onEdit(childChar, character)} 
                  onAddTagFilter={onAddTagFilter} 
                  isNested={true} 
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
