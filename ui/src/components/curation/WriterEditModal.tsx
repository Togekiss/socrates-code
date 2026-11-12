import React, { useState } from 'react';
import { Trash2 } from 'lucide-react';
import { api } from '../../api';
import type { WriterDetailed } from '../../types';
import { Modal, ChipInput, Button } from '../ui';

interface WriterEditModalProps {
  backupId: string;
  writer?: WriterDetailed | null;
  onClose: () => void;
  onSaved: () => void;
}

export const WriterEditModal: React.FC<WriterEditModalProps> = ({
  backupId,
  writer,
  onClose,
  onSaved,
}) => {
  const isNew = !writer || !writer.id;
  const [displayName, setDisplayName] = useState(writer?.display_name || '');
  const [aliases, setAliases] = useState<string[]>(writer?.aliases || []);
  const [discordUserId, setDiscordUserId] = useState(writer?.discord_user_id || '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = async () => {
    if (!displayName.trim()) {
      setError('Display name is required.');
      return;
    }

    const aliasesArray = aliases.map(s => s.trim()).filter(Boolean);

    setSaving(true);
    setError(null);
    try {
      if (isNew) {
        await api.createWriter(backupId, {
          display_name: displayName.trim(),
          aliases: aliasesArray,
          discord_user_id: discordUserId.trim() || undefined,
        });
      } else {
        await api.updateWriter(backupId, writer.id, {
          display_name: displayName.trim(),
          aliases: aliasesArray,
          discord_user_id: discordUserId.trim() || null,
        });
      }
      onSaved();
      onClose();
    } catch (err: unknown) {
      setError((err as Error).message || `Failed to ${isNew ? 'create' : 'update'} writer.`);
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (isNew || !writer?.id) return;
    if (
      !window.confirm(
        `Are you sure you want to delete writer "${writer.display_name}"? Characters written by them will become unassigned.`
      )
    ) {
      return;
    }

    setSaving(true);
    setError(null);
    try {
      await api.deleteWriter(backupId, writer.id);
      onSaved();
      onClose();
    } catch (err: unknown) {
      setError((err as Error).message || 'Failed to delete writer.');
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
            Delete Writer
          </Button>
        )}
      </div>

      <div className="flex-row items-center gap-sm">
        <Button variant="ghost" onClick={onClose} disabled={saving}>
          Cancel
        </Button>
        <Button variant="primary" onClick={handleSave} loading={saving}>
          {isNew ? 'Create Writer' : 'Save Changes'}
        </Button>
      </div>
    </div>
  );

  return (
    <Modal
      isOpen={true}
      onClose={onClose}
      title={isNew ? 'Create New Writer' : `Edit Writer: ${writer.display_name}`}
      size="md"
      footer={modalFooter}
    >
      <div className="flex-col gap-md">
        {error && (
          <div className="banner-danger">
            <span>{error}</span>
          </div>
        )}

        {/* Display Name */}
        <div className="form-group">
          <label htmlFor="writer-name" className="form-label">
            Display Name
          </label>
          <input
            id="writer-name"
            type="text"
            className="input"
            value={displayName}
            onChange={e => setDisplayName(e.target.value)}
            placeholder="e.g. JaneDoe, WriterAlias"
          />
        </div>

        {/* Aliases ChipInput */}
        <ChipInput
          id="writer-aliases"
          label="Aliases & Nicknames"
          values={aliases}
          onChange={setAliases}
          placeholder="Type alias and press Enter..."
        />

        {/* Discord User Snowflake */}
        <div className="form-group">
          <label htmlFor="writer-discord-id" className="form-label">
            Discord User ID (Snowflake)
          </label>
          <input
            id="writer-discord-id"
            type="text"
            className="input"
            value={discordUserId}
            onChange={e => setDiscordUserId(e.target.value)}
            placeholder="e.g. 123456789012345678"
          />
          <span className="form-hint">
            Links this profile to a Discord user ID for &quot;★ By Me&quot; character filtering.
          </span>
        </div>
      </div>
    </Modal>
  );
};
