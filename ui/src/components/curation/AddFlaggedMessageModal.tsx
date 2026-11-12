import React, { useState } from 'react';
import { Plus } from 'lucide-react';
import { Modal, Button } from '../ui';
import { api } from '../../api';
import type { FlaggedMessage } from '../../types';

interface AddFlaggedMessageModalProps {
  backupId: string;
  onClose: () => void;
  onSuccess: (message: FlaggedMessage) => void;
}

export const AddFlaggedMessageModal: React.FC<AddFlaggedMessageModalProps> = ({
  backupId,
  onClose,
  onSuccess,
}) => {
  const [discordLink, setDiscordLink] = useState('');
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!discordLink.trim()) {
      setError('Please provide a Discord message link.');
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const res = await api.addManualFlaggedMessage(backupId, {
        discord_link: discordLink.trim(),
        note: note.trim() || undefined,
      });
      onSuccess(res);
      onClose();
    } catch (err: unknown) {
      setError((err as Error).message || 'Failed to add manual flagged message.');
      setSaving(false);
    }
  };

  const modalTitle = (
    <div className="flex-row items-center gap-xs">
      <Plus size={18} className="text-accent" />
      <span>Add Flagged Message</span>
    </div>
  );

  const footer = (
    <div className="flex-row justify-end gap-xs w-full">
      <Button
        variant="ghost"
        size="sm"
        onClick={onClose}
        disabled={saving}
      >
        Cancel
      </Button>
      <Button
        variant="primary"
        size="sm"
        onClick={handleSubmit}
        disabled={saving || !discordLink.trim()}
        loading={saving}
        icon={<Plus size={14} />}
      >
        Add to Review Queue
      </Button>
    </div>
  );

  return (
    <Modal
      isOpen={true}
      onClose={onClose}
      title={modalTitle}
      size="md"
      footer={footer}
    >
      <form onSubmit={handleSubmit} className="flex-col gap-md">
        {error && (
          <div className="banner-danger">
            <span className="text-md">{error}</span>
          </div>
        )}

        <div className="flex-col gap-xs">
          <label className="text-primary text-sm font-semibold">
            Discord Message Link <span className="text-danger">*</span>
          </label>
          <input
            type="text"
            required
            placeholder="https://discord.com/channels/123.../456.../789..."
            value={discordLink}
            onChange={e => setDiscordLink(e.target.value)}
            className="input"
          />
          <span className="text-muted text-sm">
            Any message in this backup can be flagged for character attribution or OOC exclusion.
          </span>
        </div>

        <div className="flex-col gap-xs">
          <label className="text-primary text-sm font-semibold">
            Curator Note (Optional)
          </label>
          <input
            type="text"
            placeholder="e.g. Mistyped tupper prefix or OOC comment"
            value={note}
            onChange={e => setNote(e.target.value)}
            className="input"
          />
        </div>
      </form>
    </Modal>
  );
};
