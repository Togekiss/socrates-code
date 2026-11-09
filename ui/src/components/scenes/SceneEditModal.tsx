import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { X, Save, Loader2, Tag, Trash2 } from 'lucide-react';
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

  const sceneIdentifier = (scene as any).scene_pk ?? (scene as any).pk ?? scene.scene_key ?? scene.id;
  const isSession = scene.kind === 'session';
  const itemType = isSession ? 'session' : 'scene';
  const itemTypeCapital = isSession ? 'Session' : 'Scene';
  const modalTitle = `Edit ${itemTypeCapital} Name`;
  const channelDisplay = scene.category && scene.channel ? `${scene.category} > #${scene.channel}` : (scene.channel || 'Channel');

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !saving) onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [saving, onClose]);

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

  return createPortal(
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.75)',
        zIndex: 1000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backdropFilter: 'blur(4px)',
        padding: '1rem',
      }}
      onClick={e => {
        if (e.target === e.currentTarget && !saving) onClose();
      }}
    >
      <div
        style={{
          background: 'var(--bg-primary)',
          border: '1px solid var(--border-color)',
          borderRadius: '8px',
          maxWidth: '520px',
          width: '100%',
          padding: '1.5rem',
          boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5), 0 8px 10px -6px rgba(0, 0, 0, 0.5)',
          display: 'flex',
          flexDirection: 'column',
          gap: '1rem',
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '1.15rem', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
              <Tag size={18} style={{ color: 'var(--accent-secondary)' }} />
              {modalTitle}
            </h3>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
              {channelDisplay} {scene.thread_name ? `(${scene.thread_name})` : ''} • <span style={{ fontFamily: 'monospace' }}>{scene.scene_key}</span>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-secondary)',
              cursor: saving ? 'not-allowed' : 'pointer',
              padding: '0.25rem',
              display: 'flex',
              alignItems: 'center',
              borderRadius: '4px',
            }}
          >
            <X size={18} />
          </button>
        </div>

        {error && (
          <div
            style={{
              background: 'rgba(239, 68, 68, 0.15)',
              border: '1px solid var(--danger)',
              color: '#f87171',
              padding: '0.55rem 0.75rem',
              borderRadius: '6px',
              fontSize: '0.85rem',
            }}
          >
            {error}
          </div>
        )}

        {/* Edit Form */}
        <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
            <label style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
              Custom Name
            </label>
            <input
              ref={inputRef}
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder={isSession ? 'e.g., Casual Banter at 2AM' : 'e.g., The Coffee Shop Meeting'}
              disabled={saving}
              maxLength={128}
              style={{
                width: '100%',
                padding: '0.55rem 0.75rem',
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                color: 'var(--text-primary)',
                borderRadius: '6px',
                fontSize: '0.9rem',
                outline: 'none',
                boxSizing: 'border-box',
              }}
            />
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              Give this {itemType} a descriptive label. Leave blank or clear to reset to default.
            </span>
          </div>

          {/* Action Buttons for Custom Name */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.5rem' }}>
            {scene.custom_name ? (
              <button
                type="button"
                onClick={handleClear}
                disabled={saving}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  padding: '0.45rem 0.75rem',
                  background: 'rgba(239, 68, 68, 0.12)',
                  border: '1px solid rgba(239, 68, 68, 0.35)',
                  color: '#f87171',
                  borderRadius: '6px',
                  fontSize: '0.82rem',
                  fontWeight: 500,
                  cursor: saving ? 'not-allowed' : 'pointer',
                }}
              >
                <Trash2 size={13} /> Clear Name
              </button>
            ) : <div />}

            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button
                type="button"
                onClick={onClose}
                disabled={saving}
                style={{
                  padding: '0.45rem 0.9rem',
                  background: 'transparent',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-secondary)',
                  borderRadius: '6px',
                  fontSize: '0.85rem',
                  cursor: saving ? 'not-allowed' : 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={saving}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  padding: '0.45rem 1rem',
                  background: 'var(--accent-secondary)',
                  border: 'none',
                  color: '#fff',
                  borderRadius: '6px',
                  fontSize: '0.85rem',
                  fontWeight: 600,
                  cursor: saving ? 'not-allowed' : 'pointer',
                  opacity: saving ? 0.7 : 1,
                }}
              >
                {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                {saving ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </form>

        {/* Merge Section */}
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
    </div>,
    document.body
  );
};
