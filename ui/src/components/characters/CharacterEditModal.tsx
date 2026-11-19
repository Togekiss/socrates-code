import React, { useState, useEffect, useMemo } from 'react';
import { X, Users, AlertTriangle } from 'lucide-react';
import { api } from '../../api';
import type { Character, CharacterGroup, WriterDetailed } from '../../types';
import { getCharacterVersionList } from '../../utils/characters';
import { Modal, ChipInput, Button, CharacterPicker, WriterPicker } from '../ui';

interface CharacterEditModalProps {
  backupId: string;
  character: Character;
  parentCharacter?: Character;
  allCharacters?: Character[];
  allGroups?: CharacterGroup[];
  allWriters?: WriterDetailed[];
  onWriterCreated?: (writer: WriterDetailed) => void;
  isParticipantMode?: boolean;
  selfWriterId?: number | null;
  selfCharacterIds?: number[];
  onClose: () => void;
  onSaved: () => void;
}

export const CharacterEditModal: React.FC<CharacterEditModalProps> = ({
  backupId,
  character,
  parentCharacter,
  allCharacters = [],
  allGroups,
  allWriters,
  onWriterCreated,
  isParticipantMode = false,
  selfWriterId = null,
  selfCharacterIds = [],
  onClose,
  onSaved,
}) => {
  const [tags, setTags] = useState<string[]>(character.tags || []);
  const [names, setNames] = useState<string[]>(character.names || []);
  const [writers, setWriters] = useState<WriterDetailed[]>(allWriters ?? []);
  const [loadingWriters, setLoadingWriters] = useState(false);
  const [writerId, setWriterId] = useState<number | null>(() => {
    if (character.writer_id != null) return character.writer_id;
    if (allWriters && character.writer && character.writer.length > 0) {
      const targetNames = new Set(character.writer.map(w => w.trim().toLowerCase()).filter(Boolean));
      const matched = allWriters.find(
        w =>
          targetNames.has(w.display_name.trim().toLowerCase()) ||
          (w.aliases || []).some(a => targetNames.has(a.trim().toLowerCase()))
      );
      if (matched) return matched.id;
    }
    return null;
  });

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [actionState, setActionState] = useState<'idle' | 'merge' | 'nest'>('idle');
  const [targetId, setTargetId] = useState<number | null>(null);
  const [versionType, setVersionType] = useState<string>('alter_ego');

  // Character Groups state
  const [groups, setGroups] = useState<CharacterGroup[]>(allGroups ?? []);
  const [selectedGroupId, setSelectedGroupId] = useState<number | ''>('');
  const [updatingGroup, setUpdatingGroup] = useState(false);

  useEffect(() => {
    if (allWriters) {
      setWriters(allWriters);
      return;
    }
    if (isParticipantMode) return;
    setLoadingWriters(true);
    api
      .getWritersDetailed(backupId)
      .then(wList => {
        if (Array.isArray(wList)) {
          setWriters(wList);
          if (character.writer_id == null && character.writer && character.writer.length > 0) {
            const targetNames = new Set(character.writer.map(w => w.trim().toLowerCase()).filter(Boolean));
            const matched = wList.find(
              w =>
                targetNames.has(w.display_name.trim().toLowerCase()) ||
                (w.aliases || []).some(a => targetNames.has(a.trim().toLowerCase()))
            );
            if (matched) setWriterId(matched.id);
          }
        }
      })
      .catch(console.error)
      .finally(() => setLoadingWriters(false));
  }, [backupId, isParticipantMode, allWriters, character.writer_id, character.writer]);

  useEffect(() => {
    if (allGroups) {
      setGroups(allGroups);
      const current = allGroups.find(g =>
        (g.members || []).some(m => (typeof m === 'object' ? m.id === character.id : m === character.id))
      );
      setSelectedGroupId(current ? current.id : '');
      return;
    }
    if (isParticipantMode) return;
    api
      .getGroups(backupId)
      .then(gList => {
        if (Array.isArray(gList)) {
          setGroups(gList);
          const current = gList.find(g =>
            (g.members || []).some(m => (typeof m === 'object' ? m.id === character.id : m === character.id))
          );
          if (current) setSelectedGroupId(current.id);
        }
      })
      .catch(console.error);
  }, [backupId, character.id, isParticipantMode, allGroups]);

  const currentAssignedGroup = groups.find(g =>
    (g.members || []).some(m => (typeof m === 'object' ? m.id === character.id : m === character.id))
  );

  const handleJoinGroup = async () => {
    if (selectedGroupId === '') return;
    const targetGroup = groups.find(g => g.id === selectedGroupId);
    if (!targetGroup) return;
    setUpdatingGroup(true);
    try {
      const existingMemberIds = (targetGroup.members || []).map(m => (typeof m === 'object' ? m.id : m));
      const updatedMembers = Array.from(new Set([...existingMemberIds, character.id]));
      await api.updateGroup(backupId, targetGroup.id, { member_ids: updatedMembers });
      const refreshedGroups = await api.getGroups(backupId);
      setGroups(refreshedGroups);
      onSaved();
    } catch (err: unknown) {
      setError((err as Error).message || 'Failed to join group.');
    } finally {
      setUpdatingGroup(false);
    }
  };

  const handleLeaveGroup = async () => {
    if (!currentAssignedGroup) return;
    setUpdatingGroup(true);
    try {
      const existingMemberIds = (currentAssignedGroup.members || []).map(m => (typeof m === 'object' ? m.id : m));
      const updatedMembers = existingMemberIds.filter(mid => mid !== character.id);
      await api.updateGroup(backupId, currentAssignedGroup.id, { member_ids: updatedMembers });
      const refreshedGroups = await api.getGroups(backupId);
      setGroups(refreshedGroups);
      setSelectedGroupId('');
      onSaved();
    } catch (err: unknown) {
      setError((err as Error).message || 'Failed to leave group.');
    } finally {
      setUpdatingGroup(false);
    }
  };

  const mergeNestCandidates = useMemo(() => {
    if (!allCharacters) return [];
    return allCharacters.filter(
      c =>
        c.id !== character.id &&
        c.parent_id == null &&
        (!isParticipantMode ||
          (selfWriterId != null &&
            (c.writer_id === selfWriterId || selfCharacterIds.includes(c.id))))
    );
  }, [allCharacters, character.id, isParticipantMode, selfWriterId, selfCharacterIds]);

  const handleMerge = async () => {
    if (!targetId) return;
    if (!window.confirm('Are you sure you want to merge? This action cannot be undone.')) return;
    setSaving(true);
    try {
      await api.mergeCharacters(backupId, character.id, targetId);
      onSaved();
      onClose();
    } catch (e: unknown) {
      setError((e as Error).message);
      setSaving(false);
    }
  };

  const handleNest = async () => {
    if (!targetId) return;
    setSaving(true);
    try {
      await api.nestCharacter(backupId, character.id, targetId, versionType);
      onSaved();
      onClose();
    } catch (e: unknown) {
      setError((e as Error).message);
      setSaving(false);
    }
  };

  const toggleTag = (tag: string, exclusiveGroup?: string[]) => {
    let newTags = [...tags];
    if (newTags.includes(tag)) {
      newTags = newTags.filter(t => t !== tag);
    } else {
      if (exclusiveGroup) {
        newTags = newTags.filter(t => !exclusiveGroup.includes(t));
      }
      newTags.push(tag);
    }
    setTags(newTags);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.updateCharacter(
        backupId,
        character.id,
        isParticipantMode ? { tags, names } : { tags, names, writer_id: writerId }
      );
      onSaved();
      onClose();
    } catch (e: unknown) {
      setError((e as Error).message);
      setSaving(false);
    }
  };

  const handleUnnest = async () => {
    if (!window.confirm('Are you sure you want to turn this character into a main version?')) return;
    setSaving(true);
    try {
      await api.unnestCharacter(backupId, character.id);
      onSaved();
      onClose();
    } catch (e: unknown) {
      setError((e as Error).message);
      setSaving(false);
    }
  };

  const hasNested = getCharacterVersionList(character).length > 0;
  const isNested = Boolean(parentCharacter);

  const modalFooter = (
    <div className="flex-row items-center justify-end gap-sm">
      <Button variant="ghost" onClick={onClose} disabled={saving}>
        Cancel
      </Button>
      <Button variant="primary" onClick={handleSave} loading={saving}>
        Save Changes
      </Button>
    </div>
  );

  return (
    <Modal
      isOpen={true}
      onClose={onClose}
      title={`Edit Character #${character.id}`}
      size="lg"
      footer={modalFooter}
    >
      <div className="flex-col gap-lg">
        {error && (
          <div className="banner-danger">
            <AlertTriangle size={16} />
            <span>{error}</span>
          </div>
        )}

        <ChipInput
          label="Names & Aliases"
          values={names}
          onChange={setNames}
          placeholder="Type alias and press Enter..."
        />

        {!isParticipantMode && (
          <div className="form-group">
            <label className="form-label">Writer</label>
            <WriterPicker
              writers={writers}
              selectedIds={writerId != null ? [writerId] : []}
              onChange={ids => setWriterId(ids[0] ?? null)}
              multiple={false}
              variant="inline"
              allowUnassigned={true}
              allowCreate={true}
              backupId={backupId}
              loading={loadingWriters}
              disabled={saving}
              maxListHeight={180}
              onWriterCreated={created => {
                setWriters(prev =>
                  [...prev.filter(w => w.id !== created.id), created].sort((a, b) =>
                    a.display_name.localeCompare(b.display_name)
                  )
                );
                onWriterCreated?.(created);
              }}
            />
          </div>
        )}

        {/* Tags */}
        <div className="form-group">
          <label className="form-label">Classification Tags</label>
          <div className="flex-col gap-xs">
            <div className="flex-row items-center gap-sm">
              <span className="form-hint" style={{ width: '60px' }}>Status:</span>
              <div className="flex-row items-center gap-xs">
                {['active', 'inactive'].map(tag => (
                  <Button
                    key={tag}
                    variant={tags.includes(tag) ? 'primary' : 'secondary'}
                    size="xs"
                    onClick={() => toggleTag(tag, ['active', 'inactive'])}
                  >
                    {tag}
                  </Button>
                ))}
              </div>
            </div>

            <div className="flex-row items-center gap-sm">
              <span className="form-hint" style={{ width: '60px' }}>Canon:</span>
              <div className="flex-row items-center gap-xs">
                {['canon', 'oc'].map(tag => (
                  <Button
                    key={tag}
                    variant={tags.includes(tag) ? 'primary' : 'secondary'}
                    size="xs"
                    onClick={() => toggleTag(tag, ['canon', 'oc'])}
                  >
                    {tag}
                  </Button>
                ))}
              </div>
            </div>

            <div className="flex-row items-center gap-sm">
              <span className="form-hint" style={{ width: '60px' }}>Type:</span>
              <div className="flex-row items-center gap-xs flex-wrap">
                {['npc', 'familiar', 'alter_ego'].map(tag => (
                  <Button
                    key={tag}
                    variant={tags.includes(tag) ? 'primary' : 'secondary'}
                    size="xs"
                    onClick={() => toggleTag(tag, ['npc', 'familiar', 'alter_ego'])}
                  >
                    {tag.replace('_', ' ')}
                  </Button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Group Membership */}
        {!isParticipantMode && (
        <div className="form-group" style={{ borderTop: '1px solid var(--border-color)', paddingTop: '0.75rem' }}>
          <label className="form-label">
            <span className="flex-row items-center gap-xs">
              <Users size={14} /> Character Group Membership
            </span>
          </label>
          {currentAssignedGroup ? (
            <div className="panel-surface flex-row items-center justify-between" style={{ padding: '0.65rem 0.85rem' }}>
              <div>
                <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '0.9rem' }}>
                  {currentAssignedGroup.names?.[0] || `Group #${currentAssignedGroup.id}`}
                </div>
                {currentAssignedGroup.names && currentAssignedGroup.names.length > 1 && (
                  <div className="form-hint">
                    Aliases: {currentAssignedGroup.names.slice(1).join(', ')}
                  </div>
                )}
              </div>
              <Button
                variant="danger"
                size="xs"
                onClick={handleLeaveGroup}
                loading={updatingGroup}
              >
                Leave Group
              </Button>
            </div>
          ) : (
            <div className="flex-row items-center gap-sm">
              <select
                className="select"
                value={selectedGroupId}
                onChange={e => setSelectedGroupId(e.target.value ? Number(e.target.value) : '')}
              >
                <option value="">-- No Group (Individual Character) --</option>
                {groups.map(g => (
                  <option key={g.id} value={g.id}>
                    {g.names?.[0]} ({g.members?.length || 0} members)
                  </option>
                ))}
              </select>
              <Button
                variant="secondary"
                size="sm"
                onClick={handleJoinGroup}
                disabled={selectedGroupId === ''}
                loading={updatingGroup}
              >
                Join
              </Button>
            </div>
          )}
        </div>
        )}

        {/* Advanced Actions (Merge / Nest) */}
        <div className="form-group" style={{ borderTop: '1px solid var(--border-color)', paddingTop: '0.75rem' }}>
          <label className="form-label">Advanced Actions</label>

          {actionState === 'idle' ? (
            <div className="flex-col gap-xs">
              {isNested && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={handleUnnest}
                  disabled={saving}
                >
                  Turn into a main version
                </Button>
              )}

              {hasNested && !isNested && (
                <div className="form-hint">
                  This character has other versions. Move them to other entries before moving this one.
                </div>
              )}

              {!hasNested && !isNested && (
                <div className="flex-row items-center gap-sm">
                  {!isParticipantMode && (
                    <Button
                      variant="secondary"
                      size="sm"
                      className="flex-1"
                      onClick={() => setActionState('merge')}
                    >
                      Merge with existing...
                    </Button>
                  )}
                  <Button
                    variant="secondary"
                    size="sm"
                    className="flex-1"
                    onClick={() => setActionState('nest')}
                  >
                    Turn into version of...
                  </Button>
                </div>
              )}
            </div>
          ) : (
            <div className="panel-surface flex-col gap-sm" style={{ padding: '0.85rem' }}>
              <div className="flex-row items-center justify-between">
                <strong style={{ fontSize: '0.875rem', color: 'var(--text-primary)' }}>
                  {actionState === 'merge' ? 'Merge Character' : 'Nest Character'}
                </strong>
                <button
                  type="button"
                  className="modal-close"
                  onClick={() => {
                    setActionState('idle');
                    setTargetId(null);
                  }}
                  aria-label="Cancel action"
                >
                  <X size={14} />
                </button>
              </div>

              <CharacterPicker
                characters={mergeNestCandidates}
                selectedIds={targetId != null ? [targetId] : []}
                onChange={ids => setTargetId(ids[0] ?? null)}
                multiple={false}
                includeVersions={actionState === 'merge'}
                variant="inline"
                placeholder="Search target character by name, alias, or ID..."
                maxListHeight={180}
              />

              {targetId != null && (
                <div className="flex-col gap-sm" style={{ marginTop: '0.25rem' }}>
                  {actionState === 'nest' && (
                    <div className="form-group" style={{ marginBottom: 0 }}>
                      <label className="form-label">Version Type</label>
                      <select
                        className="select"
                        value={versionType}
                        onChange={e => setVersionType(e.target.value)}
                      >
                        <option value="alter_ego">Alter Ego</option>
                        <option value="familiar">Familiar</option>
                        <option value="npc">NPC</option>
                        <option value="different_writer">Different Writer</option>
                      </select>
                    </div>
                  )}

                  <Button
                    variant="primary"
                    size="sm"
                    onClick={actionState === 'merge' ? handleMerge : handleNest}
                    loading={saving}
                  >
                    {actionState === 'merge' ? 'Confirm Merge' : 'Confirm Nesting'}
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
};
