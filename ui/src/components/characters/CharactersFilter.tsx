import React, { useState } from 'react';
import { Search, Filter, X, Hash } from 'lucide-react';

interface CharactersFilterProps {
  nameFilter: string;
  setNameFilter: (v: string) => void;
  writerFilter: string;
  setWriterFilter: (v: string) => void;
  tagsFilter: string[];
  setTagsFilter: (v: string[]) => void;
  availableTags?: string[];
}

export const CharactersFilter: React.FC<CharactersFilterProps> = ({
  nameFilter, setNameFilter,
  writerFilter, setWriterFilter,
  tagsFilter, setTagsFilter,
  availableTags = []
}) => {
  const [collapsed, setCollapsed] = useState(false);

  const handleSelectTag = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const tag = e.target.value;
    if (tag && !tagsFilter.includes(tag)) {
      setTagsFilter([...tagsFilter, tag]);
    }
    // reset selection
    e.target.value = '';
  };

  const removeTag = (tagToRemove: string) => {
    setTagsFilter(tagsFilter.filter(t => t !== tagToRemove));
  };

  return (
    <div style={{ background: 'var(--bg-secondary)', borderRadius: '8px', border: '1px solid var(--border-color)', marginBottom: '1rem' }}>
      
      <div 
        onClick={() => setCollapsed(!collapsed)}
        style={{ padding: '0.75rem 1rem', display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', userSelect: 'none' }}
      >
        <Filter size={16} color="var(--accent-secondary)" />
        <strong style={{ fontSize: '0.9rem', color: 'var(--text-primary)' }}>Filters</strong>
        {(nameFilter || writerFilter || tagsFilter.length > 0) && (
          <span style={{ fontSize: '0.75rem', background: 'var(--accent-primary)', color: '#000', padding: '0.1rem 0.4rem', borderRadius: '12px', fontWeight: 'bold', marginLeft: 'auto' }}>Active</span>
        )}
      </div>

      {!collapsed && (
        <div style={{ padding: '1rem', borderTop: '1px solid var(--border-color)', display: 'flex', flexWrap: 'wrap', gap: '1rem' }}>
          
          <div style={{ flex: '1 1 200px' }}>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>Character Name</label>
            <div style={{ position: 'relative' }}>
              <Search size={14} style={{ position: 'absolute', left: '0.5rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
              <input 
                type="text" 
                value={nameFilter}
                onChange={e => setNameFilter(e.target.value)}
                placeholder="Filter by name..." 
                style={{ width: '100%', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', padding: '0.5rem 0.5rem 0.5rem 2rem', borderRadius: '4px' }}
              />
            </div>
          </div>

          <div style={{ flex: '1 1 200px' }}>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>Writer</label>
            <div style={{ position: 'relative' }}>
              <Search size={14} style={{ position: 'absolute', left: '0.5rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
              <input 
                type="text" 
                value={writerFilter}
                onChange={e => setWriterFilter(e.target.value)}
                placeholder="Filter by writer..." 
                style={{ width: '100%', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', padding: '0.5rem 0.5rem 0.5rem 2rem', borderRadius: '4px' }}
              />
            </div>
          </div>

          <div style={{ flex: '1 1 300px' }}>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>Tags (AND logic)</label>
            
            <select 
              onChange={handleSelectTag}
              defaultValue=""
              style={{ width: '100%', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', padding: '0.5rem', borderRadius: '4px' }}
            >
              <option value="" disabled>Select a tag to filter...</option>
              {availableTags.filter(t => !tagsFilter.includes(t)).map(tag => (
                <option key={tag} value={tag}>{tag.replace(/_/g, ' ')}</option>
              ))}
            </select>
            
            {tagsFilter.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.5rem' }}>
                {tagsFilter.map(tag => (
                  <div key={tag} style={{ background: 'var(--accent-secondary)', color: '#000', padding: '0.2rem 0.5rem', borderRadius: '12px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                    <Hash size={12} /> {tag.replace(/_/g, ' ')}
                    <button type="button" onClick={() => removeTag(tag)} style={{ background: 'transparent', border: 'none', color: '#000', padding: 0, cursor: 'pointer', display: 'flex' }}>
                      <X size={12} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
