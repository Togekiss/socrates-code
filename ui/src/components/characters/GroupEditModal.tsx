import React, { useState } from 'react';
import { Trash2 } from 'lucide-react';
import { api } from '../../api';
import type { Character } from '../../types';
import { Modal, CharacterPicker, Button } from '../ui';

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
  const [saving, setSaving] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

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

  const modalFooter = (
    <div className="flex-row items-center justify-between w-full" style={{ width: '100%' }}>
      <div>
        {!isNew && (
          <Button
            variant="danger"
            size="sm"
            onClick={handleDelete}
            disabled={saving}
            icon={<Trash2 size={14} />}
          >
            Delete Group
          </Button>
        )}
      </div>

      <div className="flex-row items-center gap-sm">
        <Button variant="ghost" onClick={onClose} disabled={saving}>
          Cancel
        </Button>
        <Button variant="primary" onClick={handleSave} loading={saving}>
          {isNew ? 'Create Group' : 'Save Changes'}
        </Button>
      </div>
    </div>
  );

  return (
    <Modal
      isOpen={true}
      onClose={onClose}
      title={isNew ? 'Create Character Group' : `Edit Group #${group.id}`}
      size="lg"
      footer={modalFooter}
    >
      <div className="flex-col gap-md">
        {error && (
          <div className="banner-danger">
            <span>{error}</span>
          </div>
        )}

        {/* Group Names */}
        <div className="form-group">
          <label htmlFor="group-names" className="form-label">
            Group Names & Aliases
          </label>
          <input
            id="group-names"
            type="text"
            className="input"
            value={names}
            onChange={e => setNames(e.target.value)}
            placeholder="e.g. Investigation Team, Bad Guys, The Fellowship (comma-separated)"
          />
          <span className="form-hint">
            First name is used as the primary display title; remaining names act as aliases.
          </span>
        </div>

        {/* Member Picker */}
        <div className="form-group">
          <label className="form-label">
            Group Members ({memberIds.length} selected)
          </label>
          <CharacterPicker
            characters={allCharacters}
            selectedIds={memberIds}
            onChange={setMemberIds}
            multiple={true}
            placeholder="Search characters to assign to this group..."
            maxListHeight={240}
          />
        </div>
      </div>
    </Modal>
  );
};
