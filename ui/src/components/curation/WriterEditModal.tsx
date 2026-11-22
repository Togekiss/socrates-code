import React, { useEffect, useMemo, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { api } from '../../api';
import type { SeenDiscordUser, WriterDetailed } from '../../types';
import { formatDiscordUserDisplayNames } from '../../utils/formatters';
import { Modal, ChipInput, Button } from '../ui';

interface WriterEditModalProps {
  backupId: string;
  writer?: WriterDetailed | null;
  seenDiscordUsers?: SeenDiscordUser[];
  isParticipantSelfEdit?: boolean;
  onClose: () => void;
  onSaved: () => void;
}

export const WriterEditModal: React.FC<WriterEditModalProps> = ({
  backupId,
  writer,
  seenDiscordUsers,
  isParticipantSelfEdit = false,
  onClose,
  onSaved,
}) => {
  const isNew = !writer || !writer.id;
  const [displayName, setDisplayName] = useState(writer?.display_name || '');
  const [aliases, setAliases] = useState<string[]>(writer?.aliases || []);
  const [discordUserId, setDiscordUserId] = useState(writer?.discord_user_id || '');
  const [fetchedUsers, setFetchedUsers] = useState<SeenDiscordUser[]>([]);
  const [loadingUsers, setLoadingUsers] = useState(
    !isParticipantSelfEdit && seenDiscordUsers === undefined
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isParticipantSelfEdit || seenDiscordUsers !== undefined) return;
    let cancelled = false;
    api
      .getSeenDiscordUsers(backupId)
      .then(data => {
        if (!cancelled) {
          setFetchedUsers(Array.isArray(data) ? data : []);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setFetchedUsers([]);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingUsers(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [backupId, isParticipantSelfEdit, seenDiscordUsers]);

  const availableDiscordUsers = useMemo(() => {
    const source = seenDiscordUsers ?? fetchedUsers;
    return source.filter(
      u => !u.linked_writer_id || (writer?.id != null && u.linked_writer_id === writer.id)
    );
  }, [seenDiscordUsers, fetchedUsers, writer]);

  const selectedDropdownValue = useMemo(() => {
    const trimmed = discordUserId.trim();
    if (!trimmed) return '';
    return availableDiscordUsers.some(u => u.discord_user_id === trimmed) ? trimmed : '';
  }, [availableDiscordUsers, discordUserId]);

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
      } else if (isParticipantSelfEdit) {
        await api.updateWriter(backupId, writer.id, {
          display_name: displayName.trim(),
          aliases: aliasesArray,
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
        {!isNew && !isParticipantSelfEdit && (
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
      <div className="flex-col gap-lg">
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
        {!isParticipantSelfEdit && (
          <div className="form-group">
            <label htmlFor="writer-discord-user-select" className="form-label">
              Discord User ID (Snowflake)
            </label>
            <select
              id="writer-discord-user-select"
              aria-label="Select unlinked Discord user"
              className="select"
              value={selectedDropdownValue}
              disabled={loadingUsers || availableDiscordUsers.length === 0}
              onChange={e => setDiscordUserId(e.target.value)}
            >
              <option value="">
                {loadingUsers
                  ? 'Loading Discord users...'
                  : availableDiscordUsers.length > 0
                    ? 'Select an unlinked Discord user...'
                    : 'No unlinked Discord users available'}
              </option>
              {availableDiscordUsers.map(u => (
                <option key={u.discord_user_id} value={u.discord_user_id}>
                  {formatDiscordUserDisplayNames(u)} — {u.discord_user_id}
                </option>
              ))}
            </select>
            <input
              id="writer-discord-id"
              aria-label="Manual Discord User ID (Snowflake)"
              type="text"
              className="input"
              value={discordUserId}
              onChange={e => setDiscordUserId(e.target.value)}
              placeholder="Or enter Discord User ID manually (e.g. 123456789012345678)"
            />
            <span className="form-hint">
              Links this profile to a Discord user ID for &quot;★ By Me&quot; character filtering. Pick an unlinked Discord user or enter a snowflake ID manually.
            </span>
          </div>
        )}
      </div>
    </Modal>
  );
};
