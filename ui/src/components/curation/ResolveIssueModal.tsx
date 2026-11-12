import React, { useState, useEffect } from 'react';
import { Check } from 'lucide-react';
import { Modal, Button } from '../ui';
import { api } from '../../api';
import type { SceneIssue } from '../../types';

interface ResolveIssueModalProps {
  backupId: string;
  issue: SceneIssue | null;
  onClose: () => void;
  onResolved: () => void;
}

export const ResolveIssueModal: React.FC<ResolveIssueModalProps> = ({
  backupId,
  issue,
  onClose,
  onResolved,
}) => {
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setNote('');
    setError(null);
    setSaving(false);
  }, [issue]);

  if (!issue) return null;

  const handleClose = () => {
    if (saving) return;
    setError(null);
    setNote('');
    onClose();
  };

  const handleResolve = async () => {
    setSaving(true);
    setError(null);
    try {
      const resolution = issue.kind === 'auto_split' ? 'split' : 'merged';
      await api.resolveSceneIssue(backupId, issue.id, resolution, note.trim() || undefined);
      onResolved();
      onClose();
    } catch (err: unknown) {
      setError((err as Error).message || 'Failed to resolve issue.');
      setSaving(false);
    }
  };

  const modalTitle =
    issue.kind === 'auto_split'
      ? `Accept Split — Scene ${issue.scene_key}`
      : issue.kind === 'soft_boundary'
      ? `Accept Merge — Scene ${issue.scene_key}`
      : `Resolve Issue #${issue.id}`;

  const footer = (
    <div className="flex-row justify-end gap-xs w-full">
      <Button
        variant="ghost"
        size="sm"
        onClick={handleClose}
        disabled={saving}
      >
        Cancel
      </Button>
      <Button
        variant="success"
        size="sm"
        onClick={handleResolve}
        disabled={saving}
        loading={saving}
        icon={<Check size={14} />}
      >
        {issue.kind === 'auto_split'
          ? 'Accept Split'
          : issue.kind === 'soft_boundary'
          ? 'Accept Merge'
          : 'Confirm Resolution'}
      </Button>
    </div>
  );

  return (
    <Modal
      isOpen={Boolean(issue)}
      onClose={handleClose}
      title={modalTitle}
      size="md"
      footer={footer}
    >
      <div className="flex-col gap-md">
        {error && (
          <div className="banner-danger">
            <span className="text-md">{error}</span>
          </div>
        )}

        <div className="text-secondary text-md" style={{ lineHeight: 1.45 }}>
          {issue.kind === 'auto_split' ? (
            <>
              Accepting this split confirms that Socrates was correct in dividing this into{' '}
              <strong className="text-primary">Scene {issue.scene_key}</strong>
              {issue.next_scene_key && (
                <> and <strong className="text-primary">Scene {issue.next_scene_key}</strong></>
              )}{' '}
              in <strong>#{issue.channel_name}</strong>.
            </>
          ) : issue.kind === 'soft_boundary' ? (
            <>
              Accepting this merge confirms that Socrates was correct in keeping{' '}
              <strong className="text-primary">Scene {issue.scene_key}</strong> in{' '}
              <strong>#{issue.channel_name}</strong> as a single continuous scene.
            </>
          ) : (
            <>
              Marking issue for scene <strong className="text-primary">{issue.scene_key}</strong> (
              <code>{issue.kind}</code>) in <strong>#{issue.channel_name}</strong> as resolved.
            </>
          )}
        </div>

        <div className="flex-col gap-xs">
          <label className="text-secondary text-sm font-semibold">
            Reviewer Note (optional)
          </label>
          <input
            type="text"
            placeholder={
              issue.kind === 'auto_split'
                ? 'e.g. Verified separate scene'
                : issue.kind === 'soft_boundary'
                ? 'e.g. Verified continuous dialogue across split point'
                : 'e.g. Verified resolution'
            }
            value={note}
            onChange={e => setNote(e.target.value)}
            className="input"
          />
        </div>
      </div>
    </Modal>
  );
};
