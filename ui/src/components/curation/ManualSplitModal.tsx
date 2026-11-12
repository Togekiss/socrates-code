import React, { useState } from 'react';
import { Split } from 'lucide-react';
import { Modal, Button } from '../ui';
import { api } from '../../api';

interface ManualSplitModalProps {
  backupId: string;
  onClose: () => void;
  onSuccess: () => void;
}

export const ManualSplitModal: React.FC<ManualSplitModalProps> = ({
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
      await api.createManualSceneSplit(backupId, {
        discord_link: discordLink.trim(),
        note: note.trim() || undefined,
      });
      onSuccess();
      onClose();
    } catch (err: unknown) {
      setError((err as Error).message || 'Failed to create manual scene split.');
      setSaving(false);
    }
  };

  const modalTitle = (
    <div className="flex-row items-center gap-xs">
      <Split size={18} className="text-accent" />
      <span>Manual Scene Split</span>
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
        icon={<Split size={14} />}
      >
        Split Scene
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
            The scene containing this message will be split in two, with this message becoming the start of Scene 2.
          </span>
        </div>

        <div className="flex-col gap-xs">
          <label className="text-primary text-sm font-semibold">
            Curator Note (Optional)
          </label>
          <input
            type="text"
            placeholder="e.g. Timeskip or new arc start"
            value={note}
            onChange={e => setNote(e.target.value)}
            className="input"
          />
        </div>
      </form>
    </Modal>
  );
};
