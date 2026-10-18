import React, { useState, useEffect } from 'react';
import { X, Loader2 } from 'lucide-react';
import { api } from '../../api';
import type { Character, CharacterGroup } from '../../types';

interface CharacterEditModalProps {
  backupId: string;
  character: Character;
  parentCharacter?: Character;
  allCharacters?: Character[];
  onClose: () => void;
  onSaved: () => void;
}

const ChipInput = ({
  values,
  onChange,
  label,
  tooltip,
}: {
  values: string[];
  onChange: (vals: string[]) => void;
  label: string;
  tooltip?: string;
}) => {
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
    onChange(values.filter(v => v !== val));
  };

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.4rem' }}>
        <label style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontWeight: 600 }}>{label}</label>
        {tooltip && (
          <span title={tooltip} style={{ cursor: 'help', color: 'var(--accent-secondary)', fontSize: '0.8rem' }}>
            ?
          </span>
        )}
      </div>
      <div
        style={{
          background: 'var(--bg-tertiary)',
          border: '1px solid var(--border-color)',
          padding: '0.5rem',
          borderRadius: '6px',
          display: 'flex',
          flexWrap: 'wrap',
          gap: '0.4rem',
        }}
      >
        {values.map(v => (
          <div
            key={v}
            style={{
              background: 'var(--bg-secondary)',
              padding: '0.2rem 0.5rem',
              borderRadius: '4px',
              fontSize: '0.85rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.25rem',
              border: '1px solid var(--border-color)',
            }}
          >
            {v}
            <button
              onClick={() => removeValue(v)}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-secondary)',
                cursor: 'pointer',
                display: 'flex',
                padding: 0,
              }}
            >
              <X size={12} />
            </button>
          </div>
        ))}
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type and press Enter..."
          style={{
            flex: 1,
            background: 'transparent',
            border: 'none',
            color: 'white',
            outline: 'none',
            minWidth: '150px',
            fontSize: '0.85rem',
          }}
        />
      </div>
    </div>
  );
};

export const CharacterEditModal: React.FC<CharacterEditModalProps> = ({
  backupId,
  character,
  parentCharacter,
  allCharacters = [],
  onClose,
  onSaved,
}) => {
  const [tags, setTags] = useState<string[]>(character.tags || []);
  const [names, setNames] = useState<string[]>(character.names || []);
  const [writer, setWriter] = useState<string[]>(character.writer || []);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [actionState, setActionState] = useState<'idle' | 'merge' | 'nest'>('idle');
  const [targetSearch, setTargetSearch] = useState('');
  const [targetId, setTargetId] = useState<number | null>(null);
  const [versionType, setVersionType] = useState<string>('alter_ego');

  // Character Groups state
  const [groups, setGroups] = useState<CharacterGroup[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<number | ''>('');
  const [updatingGroup, setUpdatingGroup] = useState(false);

  useEffect(() => {
    api
      .getGroups(backupId)
      .then(gList => {
        if (Array.isArray(gList)) {
          setGroups(gList);
          const current = gList.find(g =>
            (g.members || []).some(m => (typeof m === 'object' ? m.id === character.id : m === character.id))
          );
          if (current) setSelectedGroupId(current.id);
        }
      })
      .catch(console.error);
  }, [backupId, character.id]);

  const currentAssignedGroup = groups.find(g =>
    (g.members || []).some(m => (typeof m === 'object' ? m.id === character.id : m === character.id))
  );

  const handleJoinGroup = async () => {
    if (selectedGroupId === '') return;
    const targetGroup = groups.find(g => g.id === selectedGroupId);
    if (!targetGroup) return;
    setUpdatingGroup(true);
    try {
      const existingMemberIds = (targetGroup.members || []).map(m => (typeof m === 'object' ? m.id : m));
      const updatedMembers = Array.from(new Set([...existingMemberIds, character.id]));
      await api.updateGroup(backupId, targetGroup.id, { member_ids: updatedMembers });
      const refreshedGroups = await api.getGroups(backupId);
      setGroups(refreshedGroups);
      onSaved();
    } catch (err: any) {
      setError(err.message || 'Failed to join group.');
    } finally {
      setUpdatingGroup(false);
    }
  };

  const handleLeaveGroup = async () => {
    if (!currentAssignedGroup) return;
    setUpdatingGroup(true);
    try {
      const existingMemberIds = (currentAssignedGroup.members || []).map(m => (typeof m === 'object' ? m.id : m));
      const updatedMembers = existingMemberIds.filter(mid => mid !== character.id);
      await api.updateGroup(backupId, currentAssignedGroup.id, { member_ids: updatedMembers });
      const refreshedGroups = await api.getGroups(backupId);
      setGroups(refreshedGroups);
      setSelectedGroupId('');
      onSaved();
    } catch (err: any) {
      setError(err.message || 'Failed to leave group.');
    } finally {
      setUpdatingGroup(false);
    }
  };

  const searchResults =
    targetSearch.length > 1 && allCharacters
      ? allCharacters
          .filter(
            c =>
              c.id !== character.id &&
              c.names?.some(n => n.toLowerCase().includes(targetSearch.toLowerCase()))
          )
          .slice(0, 5)
      : [];

  const handleMerge = async () => {
    if (!targetId) return;
    if (!window.confirm('Are you sure you want to merge? This action cannot be undone.')) return;
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
    if (!window.confirm('Are you sure you want to turn this character into a main version?')) return;
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

  const hasNested = character.versions && character.versions.length > 0;
  const isNested = Boolean(parentCharacter);

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(0,0,0,0.75)',
        zIndex: 100,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backdropFilter: 'blur(4px)',
      }}
      onClick={e => {
        if (e.target === e.currentTarget && !saving) onClose();
      }}
    >
      <div
        style={{
          background: 'var(--bg-primary)',
          width: '600px',
          maxWidth: '92vw',
          maxHeight: '90vh',
          borderRadius: '12px',
          border: '1px solid var(--border-color)',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.4)',
        }}
      >
        <div
          style={{
            padding: '1rem 1.25rem',
            borderBottom: '1px solid var(--border-color)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <h2 style={{ margin: 0, fontSize: '1.2rem', color: 'var(--text-primary)' }}>
            Edit Character (ID: {character.id})
          </h2>
          <button
            onClick={onClose}
            disabled={saving}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              display: 'flex',
            }}
          >
            <X size={20} />
          </button>
        </div>

        <div
          style={{
            padding: '1.25rem',
            display: 'flex',
            flexDirection: 'column',
            gap: '1.25rem',
            overflowY: 'auto',
          }}
        >
          {error && (
            <div
              style={{
                background: 'rgba(239, 68, 68, 0.15)',
                color: 'var(--danger)',
                border: '1px solid var(--danger)',
                padding: '0.75rem 1rem',
                borderRadius: '6px',
                fontSize: '0.9rem',
              }}
            >
              {error}
            </div>
          )}

          <ChipInput
            label="Names & Aliases"
            values={names}
            onChange={setNames}
            tooltip="Name variations, nicknames, or alternate spellings for search."
          />

          <ChipInput
            label="Writer"
            values={writer}
            onChange={setWriter}
            tooltip="Aliases or usernames of the writer associated with this character."
          />

          {/* Tags */}
          <div>
            <label
              style={{
                display: 'block',
                fontSize: '0.85rem',
                color: 'var(--text-secondary)',
                marginBottom: '0.4rem',
                fontWeight: 600,
              }}
            >
              Tags
            </label>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ width: '70px', fontSize: '0.8rem', color: 'var(--text-muted)' }}>Status:</span>
                {['active', 'inactive'].map(tag => (
                  <button
                    key={tag}
                    type="button"
                    onClick={() => toggleTag(tag, ['active', 'inactive'])}
                    style={{
                      padding: '0.2rem 0.55rem',
                      borderRadius: '4px',
                      border: '1px solid var(--border-color)',
                      background: tags.includes(tag) ? 'var(--accent-primary)' : 'var(--bg-tertiary)',
                      color: tags.includes(tag) ? '#fff' : 'var(--text-secondary)',
                      fontSize: '0.8rem',
                    }}
                  >
                    {tag}
                  </button>
                ))}
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ width: '70px', fontSize: '0.8rem', color: 'var(--text-muted)' }}>Canon:</span>
                {['canon', 'oc'].map(tag => (
                  <button
                    key={tag}
                    type="button"
                    onClick={() => toggleTag(tag, ['canon', 'oc'])}
                    style={{
                      padding: '0.2rem 0.55rem',
                      borderRadius: '4px',
                      border: '1px solid var(--border-color)',
                      background: tags.includes(tag) ? 'var(--accent-primary)' : 'var(--bg-tertiary)',
                      color: tags.includes(tag) ? '#fff' : 'var(--text-secondary)',
                      fontSize: '0.8rem',
                    }}
                  >
                    {tag}
                  </button>
                ))}
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <span style={{ width: '70px', fontSize: '0.8rem', color: 'var(--text-muted)' }}>Type:</span>
                {['npc', 'familiar', 'alter_ego'].map(tag => (
                  <button
                    key={tag}
                    type="button"
                    onClick={() => toggleTag(tag, ['npc', 'familiar', 'alter_ego'])}
                    style={{
                      padding: '0.2rem 0.55rem',
                      borderRadius: '4px',
                      border: '1px solid var(--border-color)',
                      background: tags.includes(tag) ? 'var(--accent-primary)' : 'var(--bg-tertiary)',
                      color: tags.includes(tag) ? '#fff' : 'var(--text-secondary)',
                      fontSize: '0.8rem',
                    }}
                  >
                    {tag.replace('_', ' ')}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Group Membership */}
          <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '1rem' }}>
            <label
              style={{
                display: 'block',
                fontSize: '0.85rem',
                color: 'var(--text-secondary)',
                marginBottom: '0.4rem',
                fontWeight: 600,
              }}
            >
              Character Group Membership
            </label>
            {currentAssignedGroup ? (
              <div
                style={{
                  background: 'var(--bg-tertiary)',
                  border: '1px solid var(--border-color)',
                  padding: '0.75rem',
                  borderRadius: '6px',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <div>
                  <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '0.9rem' }}>
                    {currentAssignedGroup.names?.[0] || `Group #${currentAssignedGroup.id}`}
                  </div>
                  {currentAssignedGroup.names?.length > 1 && (
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      Aliases: {currentAssignedGroup.names.slice(1).join(', ')}
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  onClick={handleLeaveGroup}
                  disabled={updatingGroup}
                  style={{
                    padding: '0.35rem 0.75rem',
                    background: 'transparent',
                    border: '1px solid var(--border-color)',
                    borderRadius: '4px',
                    color: 'var(--danger)',
                    cursor: 'pointer',
                    fontSize: '0.8rem',
                  }}
                >
                  Leave Group
                </button>
              </div>
            ) : (
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                <select
                  value={selectedGroupId}
                  onChange={e => setSelectedGroupId(e.target.value ? Number(e.target.value) : '')}
                  style={{
                    flex: 1,
                    padding: '0.5rem',
                    background: 'var(--bg-tertiary)',
                    border: '1px solid var(--border-color)',
                    borderRadius: '6px',
                    color: 'white',
                    fontSize: '0.85rem',
                  }}
                >
                  <option value="">-- No Group (Individual Character) --</option>
                  {groups.map(g => (
                    <option key={g.id} value={g.id}>
                      {g.names?.[0]} ({g.members?.length || 0} members)
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={handleJoinGroup}
                  disabled={selectedGroupId === '' || updatingGroup}
                  style={{
                    padding: '0.5rem 0.85rem',
                    background: selectedGroupId !== '' ? 'var(--accent-primary)' : 'var(--bg-tertiary)',
                    color: selectedGroupId !== '' ? '#fff' : 'var(--text-muted)',
                    fontWeight: 600,
                    border: 'none',
                    borderRadius: '6px',
                    cursor: selectedGroupId !== '' ? 'pointer' : 'default',
                    fontSize: '0.85rem',
                  }}
                >
                  Join Group
                </button>
              </div>
            )}
          </div>

          {/* Advanced Actions (Merge / Nest) */}
          <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '1rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <h4 style={{ margin: '0 0 0.5rem 0', color: 'var(--text-secondary)', fontSize: '0.85rem', fontWeight: 600 }}>
              Advanced Actions
            </h4>

            {actionState === 'idle' ? (
              <>
                {isNested && (
                  <button
                    onClick={handleUnnest}
                    disabled={saving}
                    style={{
                      textAlign: 'left',
                      padding: '0.65rem 0.85rem',
                      background: 'var(--bg-tertiary)',
                      border: '1px solid var(--border-color)',
                      borderRadius: '6px',
                      color: 'white',
                      cursor: 'pointer',
                      fontSize: '0.85rem',
                    }}
                  >
                    Turn into a main version
                  </button>
                )}

                {hasNested && !isNested && (
                  <div
                    style={{
                      padding: '0.65rem 0.85rem',
                      background: 'rgba(255,255,255,0.05)',
                      borderRadius: '6px',
                      color: 'var(--text-muted)',
                      fontSize: '0.8rem',
                    }}
                  >
                    This character has other versions. Move them to other entries before moving this one.
                  </div>
                )}

                {!hasNested && !isNested && (
                  <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <button
                      onClick={() => setActionState('merge')}
                      style={{
                        flex: 1,
                        padding: '0.6rem',
                        background: 'var(--bg-tertiary)',
                        border: '1px solid var(--border-color)',
                        borderRadius: '6px',
                        color: 'white',
                        cursor: 'pointer',
                        fontSize: '0.85rem',
                      }}
                    >
                      Merge with existing...
                    </button>
                    <button
                      onClick={() => setActionState('nest')}
                      style={{
                        flex: 1,
                        padding: '0.6rem',
                        background: 'var(--bg-tertiary)',
                        border: '1px solid var(--border-color)',
                        borderRadius: '6px',
                        color: 'white',
                        cursor: 'pointer',
                        fontSize: '0.85rem',
                      }}
                    >
                      Turn into version of...
                    </button>
                  </div>
                )}
              </>
            ) : (
              <div
                style={{
                  background: 'var(--bg-tertiary)',
                  padding: '1rem',
                  borderRadius: '6px',
                  border: '1px solid var(--border-color)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
                  <strong style={{ fontSize: '0.9rem', color: 'var(--text-primary)' }}>
                    {actionState === 'merge' ? 'Merge Character' : 'Nest Character'}
                  </strong>
                  <button
                    onClick={() => {
                      setActionState('idle');
                      setTargetId(null);
                      setTargetSearch('');
                    }}
                    style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}
                  >
                    <X size={16} />
                  </button>
                </div>

                <input
                  type="text"
                  placeholder="Search for target character..."
                  value={targetSearch}
                  onChange={e => setTargetSearch(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '0.45rem 0.75rem',
                    background: 'var(--bg-secondary)',
                    border: '1px solid var(--border-color)',
                    color: 'white',
                    borderRadius: '4px',
                    marginBottom: '0.5rem',
                    fontSize: '0.85rem',
                  }}
                />

                {targetSearch.length > 1 && !targetId && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                    {searchResults.length === 0 ? (
                      <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>No characters found.</div>
                    ) : (
                      searchResults.map(c => (
                        <button
                          key={c.id}
                          onClick={() => setTargetId(c.id)}
                          style={{
                            textAlign: 'left',
                            padding: '0.4rem 0.6rem',
                            background: 'var(--bg-secondary)',
                            border: '1px solid var(--border-color)',
                            borderRadius: '4px',
                            color: 'white',
                            cursor: 'pointer',
                            display: 'flex',
                            justifyContent: 'space-between',
                            fontSize: '0.85rem',
                          }}
                        >
                          <span>{c.names?.[0]}</span>
                          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>ID: {c.id}</span>
                        </button>
                      ))
                    )}
                  </div>
                )}

                {targetId && (
                  <div style={{ marginTop: '0.75rem', padding: '0.75rem', background: 'rgba(0,0,0,0.2)', borderRadius: '4px' }}>
                    <div style={{ marginBottom: '0.5rem', fontSize: '0.85rem' }}>Selected Target ID: {targetId}</div>
                    {actionState === 'nest' && (
                      <div style={{ marginBottom: '0.5rem' }}>
                        <label style={{ display: 'block', fontSize: '0.8rem', marginBottom: '0.3rem' }}>Version Type:</label>
                        <select
                          value={versionType}
                          onChange={e => setVersionType(e.target.value)}
                          style={{
                            width: '100%',
                            padding: '0.4rem',
                            background: 'var(--bg-secondary)',
                            border: '1px solid var(--border-color)',
                            color: 'white',
                            borderRadius: '4px',
                            fontSize: '0.85rem',
                          }}
                        >
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
                      style={{
                        width: '100%',
                        padding: '0.45rem',
                        background: 'var(--accent-primary)',
                        border: 'none',
                        color: '#fff',
                        fontWeight: 600,
                        borderRadius: '4px',
                        cursor: 'pointer',
                        fontSize: '0.85rem',
                      }}
                    >
                      {actionState === 'merge' ? 'Confirm Merge' : 'Confirm Nesting'}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '1rem 1.25rem',
            borderTop: '1px solid var(--border-color)',
            display: 'flex',
            justifyContent: 'flex-end',
            gap: '0.75rem',
            background: 'var(--bg-secondary)',
            borderRadius: '0 0 12px 12px',
          }}
        >
          <button
            onClick={onClose}
            disabled={saving}
            style={{
              padding: '0.45rem 1rem',
              background: 'transparent',
              border: '1px solid var(--border-color)',
              color: 'var(--text-primary)',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '0.85rem',
            }}
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.4rem',
              padding: '0.45rem 1.25rem',
              background: 'var(--accent-primary)',
              border: 'none',
              color: '#fff',
              fontWeight: 600,
              borderRadius: '6px',
              cursor: saving ? 'not-allowed' : 'pointer',
              fontSize: '0.85rem',
            }}
          >
            {saving && <Loader2 size={14} className="animate-spin" />}
            Save Changes
          </button>
        </div>
      </div>
    </div>
  );
};
