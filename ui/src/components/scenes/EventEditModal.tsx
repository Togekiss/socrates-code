import React, { useState } from 'react';
import { GitMerge, Scissors, Save } from 'lucide-react';
import { Modal, Button } from '../ui';
import { api } from '../../api';
import type { EventChannelEntry, EventRecord } from '../../types';

interface EventEditModalProps {
  backupId: string;
  event: EventRecord;
  allEvents: EventRecord[];
  onClose: () => void;
  onUpdated: () => void;
}

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

  return (
    <Modal
      isOpen={true}
      onClose={onClose}
      title={`Edit Event (${event.id})`}
      size="lg"
    >
      <div className="flex-col gap-lg">
        {error && (
          <div className="banner-danger">
            <span className="text-md">{error}</span>
          </div>
        )}

        {/* Section 1: Event & Channel Custom Names */}
        <form onSubmit={handleSaveMetadata} className="flex-col gap-md">
          <div className="flex-col gap-xs">
            <label className="text-secondary text-sm font-semibold">Event Name</label>
            <input
              type="text"
              placeholder="e.g. Summer Festival"
              value={name}
              onChange={e => setName(e.target.value)}
              className="input"
            />
          </div>

          <div className="flex-col gap-xs">
            <label className="text-secondary text-sm font-semibold">
              Location Names for Channels &amp; Threads
            </label>
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: '0.45rem',
                maxHeight: '220px',
                overflowY: 'auto',
                padding: '0.5rem',
                background: 'var(--bg-tertiary)',
                borderRadius: '6px',
                border: '1px solid var(--border-color)',
              }}
            >
              {allEntries.map(entry => {
                const pk = entry.scene_pk ?? entry.pk ?? 0;
                const isThread = entry.type === 'thread';
                const slotLabel = isThread ? entry.channel_name : `#${entry.channel_name}`;

                return (
                  <div
                    key={`${entry.scene_key || pk}`}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.75rem',
                      paddingLeft: isThread ? '1.5rem' : 0,
                    }}
                  >
                    <span
                      style={{
                        minWidth: '150px',
                        fontSize: '0.8rem',
                        color: isThread ? 'var(--accent-secondary)' : 'var(--text-primary)',
                        fontFamily: 'monospace',
                      }}
                    >
                      {isThread ? `↳ ${slotLabel}` : slotLabel}
                    </span>
                    <input
                      type="text"
                      placeholder={`e.g. ${isThread ? 'Side Room' : 'Courtyard'}`}
                      value={channelNames[pk] || ''}
                      onChange={e =>
                        setChannelNames({
                          ...channelNames,
                          [pk]: e.target.value,
                        })
                      }
                      className="input"
                      style={{ padding: '0.35rem 0.6rem', fontSize: '0.82rem' }}
                    />
                  </div>
                );
              })}
            </div>
          </div>

          <div className="flex-row justify-end">
            <Button
              type="submit"
              variant="primary"
              size="sm"
              loading={saving}
              icon={<Save size={14} />}
            >
              Save Names
            </Button>
          </div>
        </form>

        <hr style={{ border: 'none', borderTop: '1px solid var(--border-color)', margin: 0 }} />

        {/* Section 2: Split Event */}
        <div className="flex-col gap-sm">
          <div className="flex-row items-center gap-xs text-secondary text-md font-semibold">
            <Scissors size={16} className="text-accent" />
            <span>Split Event Channels into a New Event</span>
          </div>
          <span className="text-secondary text-sm">
            Select channels or threads to branch off into a newly created event record:
          </span>

          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '0.35rem',
              maxHeight: '160px',
              overflowY: 'auto',
              padding: '0.5rem',
              background: 'var(--bg-tertiary)',
              borderRadius: '6px',
              border: '1px solid var(--border-color)',
            }}
          >
            {allEntries.map(entry => {
              const pk = entry.scene_pk ?? entry.pk ?? 0;
              const isSelected = selectedSplitScenePks.includes(pk);
              const label = entry.custom_name
                ? `${entry.custom_name} (${entry.channel_name})`
                : `#${entry.channel_name}`;

              return (
                <label
                  key={`split-${pk}`}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    fontSize: '0.82rem',
                    cursor: 'pointer',
                    color: 'var(--text-primary)',
                  }}
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => toggleSplitScene(pk)}
                  />
                  <span>
                    {entry.type === 'thread' ? `↳ ${label} (Thread)` : label} •{' '}
                    <span className="text-secondary text-sm">{entry.message_count} msgs</span>
                  </span>
                </label>
              );
            })}
          </div>

          <div className="flex-row gap-sm items-center flex-wrap">
            <input
              type="text"
              placeholder="Name for the newly split event..."
              value={newSplitEventName}
              onChange={e => setNewSplitEventName(e.target.value)}
              className="input"
              style={{ flex: 1, minWidth: '200px' }}
            />
            <Button
              variant="secondary"
              size="sm"
              disabled={saving || selectedSplitScenePks.length === 0}
              onClick={handleSplit}
              icon={<Scissors size={14} />}
            >
              Split Selected ({selectedSplitScenePks.length})
            </Button>
          </div>
        </div>

        <hr style={{ border: 'none', borderTop: '1px solid var(--border-color)', margin: 0 }} />

        {/* Section 3: Merge Entire Event */}
        <div className="flex-col gap-sm">
          <div className="flex-row items-center gap-xs text-secondary text-md font-semibold">
            <GitMerge size={16} className="text-accent" />
            <span>Merge Entire Event into Another Event</span>
          </div>
          <span className="text-secondary text-sm">
            Combine all channels and history of this event into another target event:
          </span>

          <div className="flex-row gap-sm items-center flex-wrap">
            <select
              value={mergeTargetPk}
              onChange={e => setMergeTargetPk(e.target.value)}
              className="select"
              style={{ flex: 1, minWidth: '200px' }}
            >
              <option value="">Select target event to merge into...</option>
              {otherEvents.map(ev => (
                <option key={ev.pk} value={ev.pk}>
                  {ev.name ? `${ev.name} (${ev.id})` : ev.id} • {(ev.channels || []).length} channels
                </option>
              ))}
            </select>

            <Button
              variant="secondary"
              size="sm"
              disabled={saving || !mergeTargetPk}
              onClick={handleMerge}
              icon={<GitMerge size={14} />}
            >
              Merge Events
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
};
