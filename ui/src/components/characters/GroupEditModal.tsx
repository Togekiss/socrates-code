import React, { useState } from 'react';
import { X, Trash2, Loader2 } from 'lucide-react';
import { api } from '../../api';
import { GroupMemberPicker } from './GroupMemberPicker';
import type { Character } from '../../types';

interface GroupEditModalProps {
  backupId: string;
  group?: {
    id?: number;
    names?: string[];
    members?: Array<{ id: number; name: string }> | number[];
  } | null;
  allCharacters: Character[];
  onClose: () => void;
  onSaved: () => void;
}

export const GroupEditModal: React.FC<GroupEditModalProps> = ({
  backupId,
  group,
  allCharacters,
  onClose,
  onSaved,
}) => {
  const isNew = !group || !group.id;
  const [names, setNames] = useState<string>((group?.names || []).join(', '));
  const initialMemberIds = (group?.members || []).map(m => (typeof m === 'object' ? m.id : m));
  const [memberIds, setMemberIds] = useState<number[]>(initialMemberIds);
  const [search, setSearch] = useState<string>('');
  const [saving, setSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const toggleMember = (charId: number) => {
    if (memberIds.includes(charId)) {
      setMemberIds(memberIds.filter(id => id !== charId));
    } else {
      setMemberIds([...memberIds, charId]);
    }
  };

  const handleSave = async () => {
    const namesArray = names
      .split(',')
      .map(s => s.trim())
      .filter(Boolean);

    if (namesArray.length === 0) {
      setError('Please provide at least one group name.');
      return;
    }

    setSaving(true);
    setError(null);
    try {
      if (isNew) {
        await api.createGroup(backupId, {
          names: namesArray,
          member_ids: memberIds,
        });
      } else {
        await api.updateGroup(backupId, group.id!, {
          names: namesArray,
          member_ids: memberIds,
        });
      }
      onSaved();
      onClose();
    } catch (err: unknown) {
      setError((err as Error).message || `Failed to ${isNew ? 'create' : 'update'} group.`);
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (isNew || !group?.id) return;

    if (
      !window.confirm(
        `Are you sure you want to delete group "${group.names?.[0] || group.id}"? Member characters will not be deleted, only disassociated.`
      )
    ) {
      return;
    }

    setSaving(true);
    setError(null);
    try {
      await api.deleteGroup(backupId, group.id);
      onSaved();
      onClose();
    } catch (err: unknown) {
      setError((err as Error).message || 'Failed to delete group.');
      setSaving(false);
    }
  };

  const filteredCharacters = allCharacters.filter(c => {
    if (!search) return true;
    const q = search.toLowerCase();
    const hasNameMatch = c.names?.some(n => n.toLowerCase().includes(q));
    const hasWriterMatch = c.writer?.some(w => w.toLowerCase().includes(q));
    const hasIdMatch = String(c.id).includes(q);
    return hasNameMatch || hasWriterMatch || hasIdMatch;
  });

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(0, 0, 0, 0.75)',
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
          width: '580px',
          maxWidth: '92vw',
          maxHeight: '90vh',
          borderRadius: '12px',
          border: '1px solid var(--border-color)',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.4)',
        }}
      >
        {/* Header */}
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
            {isNew ? 'Create Character Group' : `Edit Character Group (ID: ${group.id})`}
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
              padding: '0.2rem',
            }}
          >
            <X size={20} />
          </button>
        </div>

        {/* Body Form */}
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
                border: '1px solid var(--danger)',
                color: 'var(--danger)',
                padding: '0.75rem 1rem',
                borderRadius: '6px',
                fontSize: '0.9rem',
              }}
            >
              {error}
            </div>
          )}

          {/* Group Names */}
          <div>
            <label
              style={{
                display: 'block',
                fontSize: '0.85rem',
                fontWeight: 600,
                color: 'var(--text-secondary)',
                marginBottom: '0.4rem',
              }}
            >
              Group Names
            </label>
            <input
              type="text"
              value={names}
              onChange={e => setNames(e.target.value)}
              placeholder="e.g. Phoenix Wright & Miles Edgeworth, Investigation Duo"
              style={{
                width: '100%',
                padding: '0.55rem 0.75rem',
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                borderRadius: '6px',
                color: 'white',
                fontSize: '0.9rem',
              }}
            />
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.3rem' }}>
              Comma-separated. The first name is primary display name; subsequent are aliases.
            </div>
          </div>

          {/* Members Selector */}
          <div>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: '0.4rem',
              }}
            >
              <label
                style={{
                  fontSize: '0.85rem',
                  fontWeight: 600,
                  color: 'var(--text-secondary)',
                }}
              >
                Members ({memberIds.length})
              </label>
              {memberIds.length > 0 && (
                <button
                  type="button"
                  onClick={() => setMemberIds([])}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: 'var(--text-muted)',
                    fontSize: '0.75rem',
                    cursor: 'pointer',
                  }}
                >
                  Clear all
                </button>
              )}
            </div>

            {/* Selected Chips */}
            {memberIds.length > 0 && (
              <div
                style={{
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: '0.35rem',
                  marginBottom: '0.75rem',
                  maxHeight: '80px',
                  overflowY: 'auto',
                  padding: '0.4rem',
                  background: 'var(--bg-secondary)',
                  borderRadius: '6px',
                  border: '1px solid var(--border-color)',
                }}
              >
                {memberIds.map(mid => {
                  const char = allCharacters.find(c => c.id === mid);
                  const charName = char?.name || char?.names?.[0] || `#${mid}`;
                  return (
                    <span
                      key={mid}
                      style={{
                        fontSize: '0.8rem',
                        padding: '0.15rem 0.5rem',
                        borderRadius: '4px',
                        background: 'rgba(139, 92, 246, 0.2)',
                        color: 'var(--accent-secondary)',
                        border: '1px solid rgba(139, 92, 246, 0.35)',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '0.3rem',
                      }}
                    >
                      {charName}
                      <X
                        size={12}
                        style={{ cursor: 'pointer' }}
                        onClick={() => toggleMember(mid)}
                      />
                    </span>
                  );
                })}
              </div>
            )}

            <GroupMemberPicker
              search={search}
              onSearchChange={setSearch}
              filteredCharacters={filteredCharacters}
              memberIds={memberIds}
              onToggleMember={toggleMember}
            />
          </div>
        </div>

        {/* Footer Actions */}
        <div
          style={{
            padding: '1rem 1.25rem',
            borderTop: '1px solid var(--border-color)',
            display: 'flex',
            justifyContent: isNew ? 'flex-end' : 'space-between',
            alignItems: 'center',
            background: 'var(--bg-secondary)',
            borderRadius: '0 0 12px 12px',
          }}
        >
          {!isNew && (
            <button
              onClick={handleDelete}
              disabled={saving}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.4rem',
                padding: '0.45rem 0.85rem',
                background: 'rgba(239, 68, 68, 0.15)',
                border: '1px solid var(--danger)',
                color: 'var(--danger)',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '0.85rem',
              }}
            >
              <Trash2 size={14} /> Delete Group
            </button>
          )}

          <div style={{ display: 'flex', gap: '0.5rem' }}>
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
                borderRadius: '6px',
                cursor: saving ? 'not-allowed' : 'pointer',
                fontWeight: 600,
                fontSize: '0.85rem',
              }}
            >
              {saving && <Loader2 size={14} className="animate-spin" />}
              {isNew ? 'Create Group' : 'Save Changes'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
