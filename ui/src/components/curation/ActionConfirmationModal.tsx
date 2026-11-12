import React, { useState } from 'react';
import { GitMerge, Split } from 'lucide-react';
import { Modal, Button } from '../ui';
import { api } from '../../api';
import type { SceneIssue, IssueResolution } from '../../types';

interface ActionConfirmationModalProps {
  backupId: string;
  issue: SceneIssue;
  action: 'merge' | 'split';
  onClose: () => void;
  onResolved: () => void;
}

export const ActionConfirmationModal: React.FC<ActionConfirmationModalProps> = ({
  backupId,
  issue,
  action,
  onClose,
  onResolved,
}) => {
  const [actionNotes, setActionNotes] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resolution: IssueResolution = action === 'merge' ? 'merged' : 'split';

  const handleConfirm = async () => {
    setLoading(true);
    setError(null);
    try {
      await api.resolveSceneIssue(
        backupId,
        issue.id,
        resolution,
        actionNotes.trim() || undefined
      );
      onResolved();
      onClose();
    } catch (err: unknown) {
      setError((err as Error).message || `Failed to ${action} scene.`);
      setLoading(false);
    }
  };

  const modalTitle = (
    <div className="flex-row items-center gap-xs">
      {action === 'merge' ? (
        <>
          <GitMerge size={18} className="text-accent" />
          <span>Confirm Scene Merge</span>
        </>
      ) : (
        <>
          <Split size={18} className="text-accent" />
          <span>Confirm Scene Split</span>
        </>
      )}
    </div>
  );

  const footer = (
    <div className="flex-row justify-end gap-xs w-full">
      <Button
        variant="ghost"
        size="sm"
        onClick={onClose}
        disabled={loading}
      >
        Cancel
      </Button>
      <Button
        variant={action === 'merge' ? 'primary' : 'secondary'}
        size="sm"
        onClick={handleConfirm}
        disabled={loading}
        loading={loading}
        icon={action === 'merge' ? <GitMerge size={14} /> : <Split size={14} />}
      >
        {action === 'merge' ? 'Confirm Merge' : 'Confirm Split'}
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
      <div className="flex-col gap-md">
        {error && (
          <div className="banner-danger">
            <span className="text-md">{error}</span>
          </div>
        )}

        <div className="text-md text-primary" style={{ lineHeight: 1.5 }}>
          {action === 'merge' ? (
            <>
              Merge <strong className="text-accent">Scene {issue.scene_key}</strong>
              {issue.next_scene_key && (
                <> and <strong className="text-accent">Scene {issue.next_scene_key}</strong></>
              )}{' '}
              in <strong>#{issue.channel_name}</strong> into a single continuous scene?
            </>
          ) : (
            <>
              Split <strong className="text-accent">Scene {issue.scene_key}</strong> in{' '}
              <strong>#{issue.channel_name}</strong> into two distinct scenes at message{' '}
              <code className="text-accent">{issue.candidate_message_id}</code>?
            </>
          )}
        </div>

        <div
          className="text-secondary text-md p-sm border-radius-sm"
          style={{
            background: 'var(--bg-tertiary)',
            border: '1px solid var(--border-color)',
            lineHeight: 1.45,
          }}
        >
          {action === 'merge' ? (
            <>
              This will unite both scenes, combine their character participants, and preserve this merge decision across future re-indexing scans.
            </>
          ) : (
            <>
              This will truncate the current scene before the split point, start the second scene at message{' '}
              <code>{issue.candidate_message_id}</code>, and partition participants between both parts.
            </>
          )}
        </div>

        {issue.candidate_excerpt && (
          <div className="flex-col gap-xs">
            <span className="text-muted text-sm font-semibold uppercase">
              {action === 'merge' ? 'Boundary message excerpt' : 'New scene starting message'}
            </span>
            <div
              className="text-secondary text-sm p-sm border-radius-sm"
              style={{
                fontStyle: 'italic',
                background: 'rgba(0, 0, 0, 0.25)',
                lineHeight: 1.4,
                border: '1px solid var(--border-color)',
              }}
            >
              &quot;{issue.candidate_excerpt}&quot;
            </div>
          </div>
        )}

        {/* Resolution Notes Input */}
        <div className="flex-col gap-xs">
          <label className="text-secondary text-sm font-semibold">
            Resolution Notes (optional)
          </label>
          <textarea
            value={actionNotes}
            onChange={e => setActionNotes(e.target.value)}
            placeholder={
              action === 'merge'
                ? `e.g. Merged Scene ${issue.scene_key} and ${issue.next_scene_key || 'subsequent scene'}...`
                : `e.g. Split at message ${issue.candidate_message_id}...`
            }
            rows={2}
            className="textarea"
          />
        </div>
      </div>
    </Modal>
  );
};
