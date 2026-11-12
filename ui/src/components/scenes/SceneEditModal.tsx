import React, { useState, useEffect, useRef } from 'react';
import { Tag, Save, Trash2 } from 'lucide-react';
import { Modal, Button } from '../ui';
import { api } from '../../api';
import { SceneMergeSection } from './SceneMergeSection';
import type { ChatSession, Scene } from '../../types';

interface SceneEditModalProps {
  backupId: string;
  scene: Scene | ChatSession;
  onClose: () => void;
  onUpdated: (updated?: { pk: number; scene_key: string; custom_name?: string | null }) => void;
}

export const SceneEditModal: React.FC<SceneEditModalProps> = ({
  backupId,
  scene,
  onClose,
  onUpdated,
}) => {
  const [name, setName] = useState<string>(scene.custom_name || '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const sceneIdentifier =
    scene.scene_pk ?? scene.pk ?? scene.scene_key ?? scene.id;
  const isSession = scene.kind === 'session';
  const itemType = isSession ? 'session' : 'scene';
  const itemTypeCapital = isSession ? 'Session' : 'Scene';
  const modalTitle = (
    <div className="flex-row items-center gap-xs">
      <Tag size={18} className="text-accent" />
      <span>Edit {itemTypeCapital} Name</span>
    </div>
  );

  const channelDisplay =
    scene.category && scene.channel
      ? `${scene.category} > #${scene.channel}`
      : scene.channel || 'Channel';

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSave = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const cleanName = name.trim() || null;
      const res = await api.updateSceneMetadata(backupId, sceneIdentifier, {
        custom_name: cleanName,
      });
      onUpdated({
        pk: res.pk,
        scene_key: res.scene_key || scene.scene_key,
        custom_name: cleanName,
      });
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : `Failed to update ${itemType} name`);
      setSaving(false);
    }
  };

  const handleClear = async () => {
    setName('');
    setSaving(true);
    setError(null);
    try {
      const res = await api.updateSceneMetadata(backupId, sceneIdentifier, {
        custom_name: null,
      });
      onUpdated({
        pk: res.pk,
        scene_key: res.scene_key || scene.scene_key,
        custom_name: null,
      });
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : `Failed to clear ${itemType} name`);
      setSaving(false);
    }
  };

  return (
    <Modal
      isOpen={true}
      onClose={onClose}
      title={modalTitle}
      size="md"
    >
      <div className="flex-col gap-md">
        <div className="text-secondary text-sm">
          {channelDisplay} {scene.thread_name ? `(${scene.thread_name})` : ''} •{' '}
          <span className="font-mono">{scene.scene_key}</span>
        </div>

        {error && (
          <div className="banner-danger">
            <span className="text-md">{error}</span>
          </div>
        )}

        <form onSubmit={handleSave} className="flex-col gap-md">
          <div className="flex-col gap-xs">
            <label className="text-secondary text-sm font-semibold">Custom Name</label>
            <input
              ref={inputRef}
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder={isSession ? 'e.g., Casual Banter at 2AM' : 'e.g., The Coffee Shop Meeting'}
              disabled={saving}
              maxLength={128}
              className="input"
            />
            <span className="text-muted text-sm">
              Give this {itemType} a descriptive label. Leave blank or clear to reset to default.
            </span>
          </div>

          <div className="flex-row justify-between items-center gap-sm">
            {scene.custom_name ? (
              <Button
                variant="danger"
                size="sm"
                onClick={handleClear}
                disabled={saving}
                icon={<Trash2 size={13} />}
              >
                Clear Name
              </Button>
            ) : (
              <div />
            )}

            <div className="flex-row gap-xs">
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
                type="submit"
                loading={saving}
                icon={<Save size={14} />}
              >
                Save
              </Button>
            </div>
          </div>
        </form>

        <SceneMergeSection
          backupId={backupId}
          sceneIdentifier={sceneIdentifier}
          itemType={itemType}
          itemTypeCapital={itemTypeCapital}
          disabled={saving}
          onMerged={() => {
            onUpdated();
            onClose();
          }}
          onError={msg => setError(msg)}
        />
      </div>
    </Modal>
  );
};
