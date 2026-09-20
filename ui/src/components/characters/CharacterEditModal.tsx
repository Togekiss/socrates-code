import React, { useState } from 'react';
import { X } from 'lucide-react';
import { api } from '../../api';

/**
 * CharacterEditModal.tsx
 * 
 * Component responsible for managing complex character logic such as merging, nesting,
 * unnesting, and updating attributes (names, tags, writers).
 * 
 * Design Notes:
 * - Nesting/Merging: The modal accepts a complete list of `allCharacters` to populate 
 *   dropdown selections for nesting or merging targets.
 * - The `mode` state switches the modal between 'attributes' (editing tags/names/writers),
 *   'merge' (moving all data permanently to another character), and 'nest' (becoming a 
 *   sub-character/alter-ego/familiar of a main character).
 * - Unnesting is provided as an explicit button when a `parentCharacter` prop is passed,
 *   converting the current nested character back into a top-level character.
 */

interface CharacterEditModalProps {
  backupId: string;
  character: any;
  parentCharacter?: any;
  allCharacters: any[];
  onClose: () => void;
  onSaved: () => void;
}

const ChipInput = ({ values, onChange, label, tooltip }: any) => {
  const [input, setInput] = useState('');
  
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && input.trim()) {
      e.preventDefault();
      if (!values.includes(input.trim())) {
        onChange([...values, input.trim()]);
      }
      setInput('');
    }
  };
  
  const removeValue = (val: string) => {
    onChange(values.filter((v: string) => v !== val));
  };
  
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
        <label style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>{label}</label>
        {tooltip && <span title={tooltip} style={{ cursor: 'help', color: 'var(--accent-secondary)' }}>?</span>}
      </div>
      <div style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', padding: '0.5rem', borderRadius: '4px', display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
        {values.map((v: string) => (
          <div key={v} style={{ background: 'var(--bg-secondary)', padding: '0.2rem 0.5rem', borderRadius: '4px', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
            {v} <button onClick={() => removeValue(v)} style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', display: 'flex', padding: 0 }}><X size={12} /></button>
          </div>
        ))}
        <input 
          value={input} 
          onChange={e => setInput(e.target.value)} 
          onKeyDown={handleKeyDown} 
          placeholder="Type and press Enter..."
          style={{ flex: 1, background: 'transparent', border: 'none', color: 'white', outline: 'none', minWidth: '150px' }} 
        />
      </div>
    </div>
  );
};

export const CharacterEditModal: React.FC<CharacterEditModalProps> = ({ backupId, character, parentCharacter, allCharacters, onClose, onSaved }) => {
  const [tags, setTags] = useState<string[]>(character.tags || []);
  const [names, setNames] = useState<string[]>(character.names || []);
  const [writer, setWriter] = useState<string[]>(character.writer || []);
  
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [actionState, setActionState] = useState<'idle' | 'merge' | 'nest'>('idle');
  const [targetSearch, setTargetSearch] = useState('');
  const [targetId, setTargetId] = useState<number | null>(null);
  const [versionType, setVersionType] = useState<string>('alter_ego');

  const searchResults = targetSearch.length > 1 && allCharacters
    ? allCharacters.filter(c => c.id !== character.id && c.names?.[0]?.toLowerCase().includes(targetSearch.toLowerCase())).slice(0, 5)
    : [];

  const handleMerge = async () => {
    if (!targetId) return;
    if (!window.confirm("Are you sure you want to merge? This action cannot be undone.")) return;
    setSaving(true);
    try {
      await api.mergeCharacters(backupId, character.id, targetId);
      onSaved();
      onClose();
    } catch (e: any) {
      setError(e.message);
      setSaving(false);
    }
  };

  const handleNest = async () => {
    if (!targetId) return;
    setSaving(true);
    try {
      await api.nestCharacter(backupId, character.id, targetId, versionType);
      onSaved();
      onClose();
    } catch (e: any) {
      setError(e.message);
      setSaving(false);
    }
  };

  const toggleTag = (tag: string, exclusiveGroup?: string[]) => {
    let newTags = [...tags];
    if (newTags.includes(tag)) {
      newTags = newTags.filter(t => t !== tag);
    } else {
      if (exclusiveGroup) {
        newTags = newTags.filter(t => !exclusiveGroup.includes(t));
      }
      newTags.push(tag);
    }
    setTags(newTags);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.updateCharacter(backupId, character.id, { tags, names, writer });
      onSaved();
      onClose();
    } catch (e: any) {
      setError(e.message);
      setSaving(false);
    }
  };

  const handleUnnest = async () => {
    if (!window.confirm("Are you sure you want to turn this character into a main version?")) return;
    setSaving(true);
    try {
      await api.unnestCharacter(backupId, character.id);
      onSaved();
      onClose();
    } catch (e: any) {
      setError(e.message);
      setSaving(false);
    }
  };

  const hasNested = character.other_versions && character.other_versions.length > 0;
  const isNested = !!parentCharacter;

  return (
    <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.7)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--bg-primary)', width: '600px', maxWidth: '90vw', maxHeight: '90vh', overflowY: 'auto', borderRadius: '8px', border: '1px solid var(--border-color)', display: 'flex', flexDirection: 'column' }}>
        
        <div style={{ padding: '1rem', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 style={{ margin: 0, fontSize: '1.25rem' }}>Edit Character (ID: {character.id})</h2>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer' }}><X size={20} /></button>
        </div>

        <div style={{ padding: '1rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          
          {error && <div style={{ background: 'rgba(255,0,0,0.1)', color: 'var(--error-color)', padding: '1rem', borderRadius: '4px' }}>{error}</div>}

          <ChipInput 
            label="Names" 
            values={names} 
            onChange={setNames} 
            tooltip="History of changes in the Tupperbox bot's name, or nicknames and aliases to make search easier. For different Tupper bots that act as alter egos or disguises, add a separate entry as an 'other version'" 
          />

          <ChipInput 
            label="Writer" 
            values={writer} 
            onChange={setWriter} 
            tooltip="Different names, handles and aliases of the same writer. If a character is written by two different people, each character should have its own entry and be listed as an 'other version' of the first one." 
          />

          <div>
            <label style={{ display: 'block', fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>Tags</label>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <span style={{ width: '80px', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Status:</span>
                <button onClick={() => toggleTag('active', ['active', 'inactive'])} style={{ padding: '0.2rem 0.5rem', borderRadius: '4px', border: '1px solid var(--border-color)', background: tags.includes('active') ? 'var(--accent-primary)' : 'var(--bg-tertiary)', color: tags.includes('active') ? '#000' : 'white' }}>active</button>
                <button onClick={() => toggleTag('inactive', ['active', 'inactive'])} style={{ padding: '0.2rem 0.5rem', borderRadius: '4px', border: '1px solid var(--border-color)', background: tags.includes('inactive') ? 'var(--accent-primary)' : 'var(--bg-tertiary)', color: tags.includes('inactive') ? '#000' : 'white' }}>inactive</button>
              </div>

              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <span style={{ width: '80px', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Canon:</span>
                <button onClick={() => toggleTag('canon', ['canon', 'oc'])} style={{ padding: '0.2rem 0.5rem', borderRadius: '4px', border: '1px solid var(--border-color)', background: tags.includes('canon') ? 'var(--accent-primary)' : 'var(--bg-tertiary)', color: tags.includes('canon') ? '#000' : 'white' }}>canon</button>
                <button onClick={() => toggleTag('oc', ['canon', 'oc'])} style={{ padding: '0.2rem 0.5rem', borderRadius: '4px', border: '1px solid var(--border-color)', background: tags.includes('oc') ? 'var(--accent-primary)' : 'var(--bg-tertiary)', color: tags.includes('oc') ? '#000' : 'white' }}>oc</button>
              </div>

              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <span style={{ width: '80px', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Type:</span>
                <button onClick={() => toggleTag('npc', ['npc', 'familiar', 'alter_ego'])} style={{ padding: '0.2rem 0.5rem', borderRadius: '4px', border: '1px solid var(--border-color)', background: tags.includes('npc') ? 'var(--accent-primary)' : 'var(--bg-tertiary)', color: tags.includes('npc') ? '#000' : 'white' }}>npc</button>
                <button onClick={() => toggleTag('familiar', ['npc', 'familiar', 'alter_ego'])} style={{ padding: '0.2rem 0.5rem', borderRadius: '4px', border: '1px solid var(--border-color)', background: tags.includes('familiar') ? 'var(--accent-primary)' : 'var(--bg-tertiary)', color: tags.includes('familiar') ? '#000' : 'white' }}>familiar</button>
                <button onClick={() => toggleTag('alter_ego', ['npc', 'familiar', 'alter_ego'])} style={{ padding: '0.2rem 0.5rem', borderRadius: '4px', border: '1px solid var(--border-color)', background: tags.includes('alter_ego') ? 'var(--accent-primary)' : 'var(--bg-tertiary)', color: tags.includes('alter_ego') ? '#000' : 'white' }}>alter ego</button>
              </div>

            </div>
          </div>

          <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '1.5rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <h4 style={{ margin: '0 0 0.5rem 0', color: 'var(--text-secondary)' }}>Advanced Actions</h4>
            
            {actionState === 'idle' ? (
              <>
                {isNested && (
                  <button onClick={handleUnnest} disabled={saving} style={{ textAlign: 'left', padding: '0.75rem', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', borderRadius: '4px', color: 'white', cursor: 'pointer' }}>
                    Turn into a main version
                  </button>
                )}

                {hasNested && !isNested && (
                  <div style={{ padding: '0.75rem', background: 'rgba(255,255,255,0.05)', borderRadius: '4px', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                    This character has other versions. Move them to other entries if you want to move this one.
                  </div>
                )}

                {!hasNested && !isNested && (
                  <>
                    <button onClick={() => setActionState('merge')} style={{ textAlign: 'left', padding: '0.75rem', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', borderRadius: '4px', color: 'white', cursor: 'pointer' }}>
                      Merge with an existing character...
                    </button>
                    <button onClick={() => setActionState('nest')} style={{ textAlign: 'left', padding: '0.75rem', background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)', borderRadius: '4px', color: 'white', cursor: 'pointer' }}>
                      Turn into another version of another character...
                    </button>
                  </>
                )}
              </>
            ) : (
              <div style={{ background: 'var(--bg-tertiary)', padding: '1rem', borderRadius: '4px', border: '1px solid var(--border-color)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1rem' }}>
                  <strong>{actionState === 'merge' ? 'Merge Character' : 'Nest Character'}</strong>
                  <button onClick={() => { setActionState('idle'); setTargetId(null); setTargetSearch(''); }} style={{ background: 'transparent', border: 'none', color: 'white', cursor: 'pointer' }}><X size={16} /></button>
                </div>
                
                <input 
                  type="text" 
                  placeholder="Search for target character..."
                  value={targetSearch}
                  onChange={e => setTargetSearch(e.target.value)}
                  style={{ width: '100%', padding: '0.5rem', background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', color: 'white', borderRadius: '4px', marginBottom: '0.5rem' }}
                />

                {targetSearch.length > 1 && !targetId && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                    {searchResults.length === 0 ? (
                      <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>No characters found.</div>
                    ) : (
                      searchResults.map(c => (
                        <button key={c.id} onClick={() => setTargetId(c.id)} style={{ textAlign: 'left', padding: '0.5rem', background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', borderRadius: '4px', color: 'white', cursor: 'pointer', display: 'flex', justifyContent: 'space-between' }}>
                          <span>{c.names?.[0]}</span>
                          <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>ID: {c.id}</span>
                        </button>
                      ))
                    )}
                  </div>
                )}

                {targetId && (
                  <div style={{ marginTop: '1rem', padding: '1rem', background: 'rgba(0,0,0,0.2)', borderRadius: '4px' }}>
                    <div style={{ marginBottom: '1rem' }}>Selected Target ID: {targetId}</div>
                    
                    {actionState === 'nest' && (
                      <div style={{ marginBottom: '1rem' }}>
                        <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '0.5rem' }}>Version Type:</label>
                        <select value={versionType} onChange={e => setVersionType(e.target.value)} style={{ width: '100%', padding: '0.5rem', background: 'var(--bg-secondary)', border: '1px solid var(--border-color)', color: 'white', borderRadius: '4px' }}>
                          <option value="alter_ego">Alter Ego</option>
                          <option value="familiar">Familiar</option>
                          <option value="npc">NPC</option>
                          <option value="different_writer">Different Writer</option>
                        </select>
                      </div>
                    )}
                    
                    <button 
                      onClick={actionState === 'merge' ? handleMerge : handleNest} 
                      disabled={saving} 
                      style={{ width: '100%', padding: '0.5rem', background: 'var(--accent-primary)', border: 'none', color: '#000', fontWeight: 'bold', borderRadius: '4px', cursor: 'pointer' }}
                    >
                      {actionState === 'merge' ? 'Confirm Merge' : 'Confirm Nesting'}
                    </button>
                  </div>
                )}

              </div>
            )}
            
          </div>

        </div>

        <div style={{ padding: '1rem', borderTop: '1px solid var(--border-color)', display: 'flex', justifyContent: 'flex-end', gap: '1rem', background: 'var(--bg-secondary)' }}>
          <button onClick={onClose} style={{ padding: '0.5rem 1rem', background: 'transparent', border: '1px solid var(--border-color)', color: 'white', borderRadius: '4px', cursor: 'pointer' }}>
            Cancel
          </button>
          <button onClick={handleSave} disabled={saving} style={{ padding: '0.5rem 1.5rem', background: 'var(--accent-primary)', border: 'none', color: '#000', fontWeight: 'bold', borderRadius: '4px', cursor: 'pointer' }}>
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>

      </div>
    </div>
  );
};
