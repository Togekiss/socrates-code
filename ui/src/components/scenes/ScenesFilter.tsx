import React, { useState } from 'react';
import { Filter, X } from 'lucide-react';

/**
 * ScenesFilter.tsx
 * 
 * Component responsible for rendering the complex filter sidebar in the Scenes tab.
 * 
 * Design Notes:
 * - Uses nested mapping to flatten character objects (which might contain familiars/alter egos)
 *   so they can all be selected uniformly in the dropdown `<select>`.
 * - Toggles (Alter Egos, Familiars, NPCs) automatically disable when 'AND' character logic 
 *   is selected. This is because 'AND' requires all selected base characters to be present 
 *   in the scene; adding expanded alternative versions mathematically conflicts with most 
 *   'AND' queries on a scene level unless intentionally requested via individual manual selection.
 */

interface ScenesFilterProps {
  charactersFilter: number[];
  setCharactersFilter: (v: number[]) => void;
  characterLogic: 'AND' | 'OR';
  setCharacterLogic: (v: 'AND' | 'OR') => void;
  writersFilter: string[];
  setWritersFilter: (v: string[]) => void;
  writerLogic: 'AND' | 'OR';
  setWriterLogic: (v: 'AND' | 'OR') => void;
  categoriesFilter: string[];
  setCategoriesFilter: (v: string[]) => void;
  typesFilter: string[];
  setTypesFilter: (v: string[]) => void;
  statusesFilter: string[];
  setStatusesFilter: (v: string[]) => void;
  includeAlterEgos: boolean;
  setIncludeAlterEgos: (v: boolean) => void;
  includeFamiliars: boolean;
  setIncludeFamiliars: (v: boolean) => void;
  includeNPCs: boolean;
  setIncludeNPCs: (v: boolean) => void;
  before: string;
  setBefore: (v: string) => void;
  after: string;
  setAfter: (v: string) => void;
  
  allCharacters: any[];
}

export const ScenesFilter: React.FC<ScenesFilterProps> = ({
  charactersFilter, setCharactersFilter, characterLogic, setCharacterLogic,
  writersFilter, setWritersFilter, writerLogic, setWriterLogic,
  categoriesFilter, setCategoriesFilter,
  typesFilter, setTypesFilter,
  statusesFilter, setStatusesFilter,
  includeAlterEgos, setIncludeAlterEgos,
  includeFamiliars, setIncludeFamiliars,
  includeNPCs, setIncludeNPCs,
  before, setBefore,
  after, setAfter,
  allCharacters
}) => {
  const [collapsed, setCollapsed] = useState(false);
  const [writerInput, setWriterInput] = useState('');
  const [categoryInput, setCategoryInput] = useState('');

  const addCharFilter = (id: number) => {
    if (!charactersFilter.includes(id)) setCharactersFilter([...charactersFilter, id]);
  };

  const removeCharFilter = (id: number) => setCharactersFilter(charactersFilter.filter(x => x !== id));
  
  const addWriterFilter = (e: React.FormEvent) => {
    e.preventDefault();
    if (writerInput.trim() && !writersFilter.includes(writerInput.trim())) {
      setWritersFilter([...writersFilter, writerInput.trim()]);
    }
    setWriterInput('');
  };
  const removeWriterFilter = (w: string) => setWritersFilter(writersFilter.filter(x => x !== w));

  const addCategoryFilter = (e: React.FormEvent) => {
    e.preventDefault();
    if (categoryInput.trim() && !categoriesFilter.includes(categoryInput.trim())) {
      setCategoriesFilter([...categoriesFilter, categoryInput.trim()]);
    }
    setCategoryInput('');
  };
  const removeCategoryFilter = (c: string) => setCategoriesFilter(categoriesFilter.filter(x => x !== c));

  const toggleArrayItem = (arr: string[], setArr: (v: string[]) => void, item: string) => {
    if (arr.includes(item)) setArr(arr.filter(x => x !== item));
    else setArr([...arr, item]);
  };

  const getCharName = (id: number) => {
    const main = allCharacters.find(c => c.id === id);
    if (main) return main.names?.[0];
    for (const c of allCharacters) {
      if (c.other_versions) {
        const nested = c.other_versions.find((v: any) => v.id === id);
        if (nested) return nested.names?.[0];
      }
    }
    return `Unknown (${id})`;
  };

  return (
    <div style={{ background: 'var(--bg-secondary)', borderRadius: '8px', border: '1px solid var(--border-color)', marginBottom: '1rem' }}>
      
      <div 
        onClick={() => setCollapsed(!collapsed)}
        style={{ padding: '0.75rem 1rem', display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', userSelect: 'none' }}
      >
        <Filter size={16} color="var(--accent-secondary)" />
        <strong style={{ fontSize: '0.9rem', color: 'var(--text-primary)' }}>Filters</strong>
      </div>
      
      {!collapsed && (
        <div style={{ padding: '1rem', borderTop: '1px solid var(--border-color)', display: 'flex', flexWrap: 'wrap', gap: '1.5rem' }}>
          
          {/* Characters */}
          <div style={{ flex: '1 1 300px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
              <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Characters</label>
              <button 
                onClick={() => {
                  const newLogic = characterLogic === 'AND' ? 'OR' : 'AND';
                  setCharacterLogic(newLogic);
                  if (newLogic === 'AND') {
                    setIncludeAlterEgos(false);
                    setIncludeFamiliars(false);
                    setIncludeNPCs(false);
                  }
                }} 
                style={{ fontSize: '0.7rem', padding: '0.1rem 0.4rem', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', borderRadius: '4px', cursor: 'pointer' }}
              >
                Logic: {characterLogic}
              </button>
            </div>
            
            <select 
              value="" 
              onChange={e => addCharFilter(Number(e.target.value))}
              style={{ width: '100%', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', padding: '0.5rem', borderRadius: '4px' }}
            >
              <option value="" disabled>Select character...</option>
              {allCharacters.flatMap(c => [
                <option key={c.id} value={c.id}>{c.names?.[0]}</option>,
                ...(c.other_versions || []).map((v: any) => (
                  <option key={v.id} value={v.id}>  └ {v.names?.[0]} (Alt)</option>
                ))
              ])}
            </select>
            
            {charactersFilter.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.5rem' }}>
                {charactersFilter.map(id => {
                  return (
                    <div key={id} style={{ background: 'var(--accent-secondary)', color: '#000', padding: '0.2rem 0.5rem', borderRadius: '12px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                      {getCharName(id)}
                      <button type="button" onClick={() => removeCharFilter(id)} style={{ background: 'transparent', border: 'none', color: '#000', padding: 0, cursor: 'pointer', display: 'flex' }}><X size={12} /></button>
                    </div>
                  );
                })}
              </div>
            )}
            
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.75rem' }}>
              <button 
                onClick={() => setIncludeAlterEgos(!includeAlterEgos)} 
                disabled={characterLogic === 'AND'}
                style={{ padding: '0.2rem 0.5rem', borderRadius: '4px', fontSize: '0.75rem', border: '1px solid var(--border-color)', background: includeAlterEgos ? 'var(--accent-primary)' : 'var(--bg-tertiary)', color: includeAlterEgos ? '#000' : 'white', opacity: characterLogic === 'AND' ? 0.5 : 1, cursor: characterLogic === 'AND' ? 'default' : 'pointer' }}
              >
                + Alter Egos
              </button>
              <button 
                onClick={() => setIncludeFamiliars(!includeFamiliars)} 
                disabled={characterLogic === 'AND'}
                style={{ padding: '0.2rem 0.5rem', borderRadius: '4px', fontSize: '0.75rem', border: '1px solid var(--border-color)', background: includeFamiliars ? 'var(--accent-primary)' : 'var(--bg-tertiary)', color: includeFamiliars ? '#000' : 'white', opacity: characterLogic === 'AND' ? 0.5 : 1, cursor: characterLogic === 'AND' ? 'default' : 'pointer' }}
              >
                + Familiars
              </button>
              <button 
                onClick={() => setIncludeNPCs(!includeNPCs)} 
                disabled={characterLogic === 'AND'}
                style={{ padding: '0.2rem 0.5rem', borderRadius: '4px', fontSize: '0.75rem', border: '1px solid var(--border-color)', background: includeNPCs ? 'var(--accent-primary)' : 'var(--bg-tertiary)', color: includeNPCs ? '#000' : 'white', opacity: characterLogic === 'AND' ? 0.5 : 1, cursor: characterLogic === 'AND' ? 'default' : 'pointer' }}
              >
                + NPCs
              </button>
            </div>
          </div>

          {/* Writers */}
          <div style={{ flex: '1 1 200px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
              <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Writers</label>
              <button onClick={() => setWriterLogic(writerLogic === 'AND' ? 'OR' : 'AND')} style={{ fontSize: '0.7rem', padding: '0.1rem 0.4rem', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', borderRadius: '4px', cursor: 'pointer' }}>
                Logic: {writerLogic}
              </button>
            </div>
            <form onSubmit={addWriterFilter} style={{ display: 'flex', gap: '0.5rem' }}>
              <input type="text" value={writerInput} onChange={e => setWriterInput(e.target.value)} placeholder="Add writer..." style={{ flex: 1, background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', padding: '0.5rem', borderRadius: '4px' }} />
            </form>
            {writersFilter.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.5rem' }}>
                {writersFilter.map(w => (
                  <div key={w} style={{ background: 'var(--accent-secondary)', color: '#000', padding: '0.2rem 0.5rem', borderRadius: '12px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                    {w} <button type="button" onClick={() => removeWriterFilter(w)} style={{ background: 'transparent', border: 'none', color: '#000', padding: 0, cursor: 'pointer', display: 'flex' }}><X size={12} /></button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Categories */}
          <div style={{ flex: '1 1 200px' }}>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>Category (OR)</label>
            <form onSubmit={addCategoryFilter} style={{ display: 'flex', gap: '0.5rem' }}>
              <input type="text" value={categoryInput} onChange={e => setCategoryInput(e.target.value)} placeholder="Add category..." style={{ flex: 1, background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', padding: '0.5rem', borderRadius: '4px' }} />
            </form>
            {categoriesFilter.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.5rem' }}>
                {categoriesFilter.map(c => (
                  <div key={c} style={{ background: 'var(--accent-secondary)', color: '#000', padding: '0.2rem 0.5rem', borderRadius: '12px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                    {c} <button type="button" onClick={() => removeCategoryFilter(c)} style={{ background: 'transparent', border: 'none', color: '#000', padding: 0, cursor: 'pointer', display: 'flex' }}><X size={12} /></button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Status & Type */}
          <div style={{ flex: '1 1 150px' }}>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>Status (OR)</label>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              {['closed', 'open', 'timeout'].map(s => (
                <button key={s} onClick={() => toggleArrayItem(statusesFilter, setStatusesFilter, s)} style={{ padding: '0.2rem 0.5rem', borderRadius: '4px', border: '1px solid var(--border-color)', background: statusesFilter.includes(s) ? 'var(--accent-primary)' : 'var(--bg-tertiary)', color: statusesFilter.includes(s) ? '#000' : 'white' }}>{s}</button>
              ))}
            </div>
            
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '1rem', marginBottom: '0.25rem' }}>Type (OR)</label>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              {['channel', 'thread', 'DM'].map(t => (
                <button key={t} onClick={() => toggleArrayItem(typesFilter, setTypesFilter, t)} style={{ padding: '0.2rem 0.5rem', borderRadius: '4px', border: '1px solid var(--border-color)', background: typesFilter.includes(t) ? 'var(--accent-primary)' : 'var(--bg-tertiary)', color: typesFilter.includes(t) ? '#000' : 'white' }}>{t}</button>
              ))}
            </div>
          </div>

          {/* Dates */}
          <div style={{ flex: '1 1 150px' }}>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>Before</label>
            <input type="date" value={before} onChange={e => setBefore(e.target.value)} style={{ width: '100%', padding: '0.5rem', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', borderRadius: '4px' }} />
            
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '1rem', marginBottom: '0.25rem' }}>After</label>
            <input type="date" value={after} onChange={e => setAfter(e.target.value)} style={{ width: '100%', padding: '0.5rem', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', color: 'white', borderRadius: '4px' }} />
          </div>

        </div>
      )}
    </div>
  );
};
