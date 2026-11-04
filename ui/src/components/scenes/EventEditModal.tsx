import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, ExternalLink, GitMerge, Scissors, Save, Loader2 } from 'lucide-react';
import { api } from '../../api';
import type { EventChannelEntry, EventRecord } from '../../types';

interface EventEditModalProps {
  backupId: string;
  event: EventRecord;
  allEvents: EventRecord[];
  onClose: () => void;
  onUpdated: () => void;
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '0.45rem 0.6rem',
  background: 'var(--bg-tertiary)',
  border: '1px solid var(--border-color)',
  color: 'white',
  borderRadius: '4px',
  fontSize: '0.85rem',
};

export const EventEditModal: React.FC<EventEditModalProps> = ({
  backupId,
  event,
  allEvents,
  onClose,
  onUpdated,
}) => {
  const [name, setName] = useState<string>(event.name || '');

  // Flatten channels + threads for custom_name editing
  const allEntries: EventChannelEntry[] = [];
  (event.channels || []).forEach(ch => {
    allEntries.push(ch);
    (ch.threads || []).forEach(th => allEntries.push(th));
  });

  const [channelNames, setChannelNames] = useState<Record<number, string>>(() => {
    const initial: Record<number, string> = {};
    allEntries.forEach(entry => {
      const pk = entry.scene_pk ?? entry.pk ?? 0;
      initial[pk] = entry.custom_name || '';
    });
    return initial;
  });

  // Split state
  const [selectedSplitScenePks, setSelectedSplitScenePks] = useState<number[]>([]);
  const [newSplitEventName, setNewSplitEventName] = useState<string>('');

  // Merge state
  const [mergeTargetPk, setMergeTargetPk] = useState<string>('');

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !saving) onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [saving, onClose]);

  const handleSaveMetadata = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payloadNames: Record<number, string | null> = {};
      Object.entries(channelNames).forEach(([pkStr, val]) => {
        payloadNames[Number(pkStr)] = val.trim() || null;
      });
      await api.updateEventMetadata(backupId, event.pk, {
        name: name.trim() || null,
        channel_names: payloadNames,
      });
      onUpdated();
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to update event metadata');
    } finally {
      setSaving(false);
    }
  };

  const handleSplit = async () => {
    if (selectedSplitScenePks.length === 0) return;
    setSaving(true);
    setError(null);
    try {
      await api.splitEvent(
        backupId,
        event.pk,
        selectedSplitScenePks,
        newSplitEventName.trim() || null
      );
      onUpdated();
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to split event');
    } finally {
      setSaving(false);
    }
  };

  const handleMerge = async () => {
    const otherPk = Number(mergeTargetPk);
    if (!otherPk || otherPk === event.pk) return;
    setSaving(true);
    setError(null);
    try {
      await api.mergeEvents(backupId, event.pk, otherPk, name.trim() || null);
      onUpdated();
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to merge events');
    } finally {
      setSaving(false);
    }
  };

  const toggleSplitScene = (scenePk: number) => {
    if (selectedSplitScenePks.includes(scenePk)) {
      setSelectedSplitScenePks(selectedSplitScenePks.filter(id => id !== scenePk));
    } else {
      setSelectedSplitScenePks([...selectedSplitScenePks, scenePk]);
    }
  };

  const otherEvents = allEvents.filter(ev => ev.pk !== event.pk);

  return createPortal(
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
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
          width: '640px',
          maxWidth: '92vw',
          maxHeight: '88vh',
          overflowY: 'auto',
          borderRadius: '12px',
          border: '1px solid var(--border-color)',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.4)',
          padding: '1.5rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '1.25rem',
        }}
        onClick={e => e.stopPropagation()}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h3 style={{ margin: 0, fontSize: '1.15rem', color: 'var(--text-primary)' }}>
            Edit Event ({event.id})
          </h3>
          <button
            type="button"
            onClick={onClose}
            style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer' }}
          >
            <X size={20} />
          </button>
        </div>

        {error && (
          <div style={{ padding: '0.65rem', background: 'rgba(239, 68, 68, 0.15)', border: '1px solid var(--danger)', color: 'var(--danger)', borderRadius: '6px', fontSize: '0.85rem' }}>
            {error}
          </div>
        )}

        {/* Section 1: Event & Channel Custom Names */}
        <form onSubmit={handleSaveMetadata} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.3rem' }}>
              Event Name
            </label>
            <input
              type="text"
              placeholder="e.g. Summer Festival"
              value={name}
              onChange={e => setName(e.target.value)}
              style={inputStyle}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>
              Channel Custom Names (Location Labels)
            </label>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {allEntries.map(entry => (
                <div
                  key={entry.scene_pk}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    paddingLeft: entry.type === 'thread' ? '1.25rem' : 0,
                  }}
                >
                  <span style={{ minWidth: '140px', fontSize: '0.82rem', color: 'var(--text-primary)' }}>
                    {entry.type === 'thread' ? `↳ ${entry.channel_name}` : `#${entry.channel_name}`}
                  </span>
                  <input
                    type="text"
                    placeholder="Custom location name (e.g. garden)"
                    value={channelNames[entry.scene_pk] ?? ''}
                    onChange={e =>
                      setChannelNames({ ...channelNames, [entry.scene_pk]: e.target.value })
                    }
                    style={{ ...inputStyle, flex: 1 }}
                  />
                  {entry.start?.link && (
                    <a
                      href={entry.start.link}
                      target="_blank"
                      rel="noopener noreferrer"
                      title="Open first message in Discord to check location banner"
                      style={{
                        display: 'inline-flex', alignItems: 'center', gap: '0.25rem',
                        padding: '0.35rem 0.55rem', fontSize: '0.75rem',
                        background: 'rgba(139, 92, 246, 0.2)', border: '1px solid #8b5cf6',
                        color: '#c4b5fd', borderRadius: '4px', textDecoration: 'none', whiteSpace: 'nowrap',
                      }}
                    >
                      <ExternalLink size={12} /> Discord
                    </a>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button
              type="submit"
              disabled={saving}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.4rem',
                padding: '0.5rem 1rem',
                background: 'var(--accent-primary)',
                color: '#fff',
                border: 'none',
                borderRadius: '6px',
                fontWeight: 600,
                cursor: saving ? 'not-allowed' : 'pointer',
              }}
            >
              {saving ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />}
              Save Names
            </button>
          </div>
        </form>

        {/* Section 2: Split Event */}
        {allEntries.length > 1 && (
          <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '1rem', display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
            <strong style={{ fontSize: '0.9rem', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <Scissors size={15} /> Split Channels into a New Event
            </strong>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
              {allEntries.map(entry => (
                <label
                  key={entry.scene_pk}
                  style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.82rem', cursor: 'pointer' }}
                >
                  <input
                    type="checkbox"
                    checked={selectedSplitScenePks.includes(entry.scene_pk)}
                    onChange={() => toggleSplitScene(entry.scene_pk)}
                  />
                  <span>
                    {entry.type === 'thread' ? `Thread: ${entry.channel_name}` : `#${entry.channel_name}`}
                    {entry.custom_name ? ` (${entry.custom_name})` : ''} — {entry.message_count} msgs
                  </span>
                </label>
              ))}
            </div>
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
              <input
                type="text"
                placeholder="New split event name (optional)"
                value={newSplitEventName}
                onChange={e => setNewSplitEventName(e.target.value)}
                style={{ ...inputStyle, flex: 1 }}
              />
              <button
                type="button"
                onClick={handleSplit}
                disabled={saving || selectedSplitScenePks.length === 0 || selectedSplitScenePks.length >= allEntries.length}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: '0.35rem', padding: '0.45rem 0.9rem',
                  background: 'rgba(245, 158, 11, 0.2)', border: '1px solid var(--warning)', color: '#fbbf24',
                  borderRadius: '6px', fontWeight: 600, whiteSpace: 'nowrap',
                  cursor: saving || selectedSplitScenePks.length === 0 || selectedSplitScenePks.length >= allEntries.length ? 'not-allowed' : 'pointer',
                }}
              >
                <Scissors size={14} /> Split Selected
              </button>
            </div>
          </div>
        )}

        {/* Section 3: Merge with Another Event */}
        {otherEvents.length > 0 && (
          <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '1rem', display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
            <strong style={{ fontSize: '0.9rem', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <GitMerge size={15} /> Merge Another Event into This Event
            </strong>
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
              <select
                value={mergeTargetPk}
                onChange={e => setMergeTargetPk(e.target.value)}
                style={{ ...inputStyle, flex: 1 }}
              >
                <option value="">-- Select an event to merge --</option>
                {otherEvents.map(ev => {
                  const ts = ev.start_timestamp || ev.start_at || '';
                  const dateLabel = ts ? new Date(ts).toLocaleDateString() : 'N/A';
                  return (
                    <option key={ev.pk} value={ev.pk}>
                      {ev.name || 'Unnamed Event'} ({ev.id}) — {dateLabel} ({ev.message_count} msgs)
                    </option>
                  );
                })}
              </select>
              <button
                type="button"
                onClick={handleMerge}
                disabled={saving || !mergeTargetPk}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: '0.35rem', padding: '0.45rem 0.9rem',
                  background: 'rgba(139, 92, 246, 0.2)', border: '1px solid #8b5cf6', color: '#c4b5fd',
                  borderRadius: '6px', fontWeight: 600, whiteSpace: 'nowrap',
                  cursor: saving || !mergeTargetPk ? 'not-allowed' : 'pointer',
                }}
              >
                <GitMerge size={14} /> Merge Events
              </button>
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body
  );
};
