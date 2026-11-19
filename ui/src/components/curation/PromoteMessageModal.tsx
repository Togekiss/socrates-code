import React, { useState, useEffect, useMemo } from 'react';
import { Check } from 'lucide-react';
import { Modal, Button, CharacterPicker } from '../ui';
import { api } from '../../api';
import type { FlaggedMessage, Character } from '../../types';
import { resolveCharacterName } from '../../utils/characters';

interface PromoteMessageModalProps {
  backupId: string;
  message: FlaggedMessage | null;
  allCharacters?: Character[];
  onClose: () => void;
  onPromoted: () => void;
}

export const PromoteMessageModal: React.FC<PromoteMessageModalProps> = ({
  backupId,
  message,
  allCharacters,
  onClose,
  onPromoted,
}) => {
  const suggested = message?.suggested_character;
  const [content, setContent] = useState(message?.content || '');
  const [characters, setCharacters] = useState<Character[]>(allCharacters ?? []);
  const [loadingCharacters, setLoadingCharacters] = useState(false);
  const [selectedCharacterId, setSelectedCharacterId] = useState<number | ''>(
    suggested?.char_id ?? ''
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (allCharacters) {
      setCharacters(allCharacters);
      return;
    }
    if (!backupId) return;
    setLoadingCharacters(true);
    api.getCharacters(backupId)
      .then(res => {
        if (Array.isArray(res)) {
          setCharacters(res);
        }
      })
      .catch(console.error)
      .finally(() => setLoadingCharacters(false));
  }, [backupId, allCharacters]);

  const fallbackOptions = useMemo(() => {
    if (!suggested) return undefined;
    return [
      {
        id: suggested.char_id,
        name: suggested.name,
        writerName: suggested.writer_name,
      },
    ];
  }, [suggested]);

  if (!message) return null;

  const stripCharacterPrefix = (charName: string) => {
    const escapedName = charName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const prefixRegex = new RegExp(`^\\s*${escapedName}\\s*:\\s*`, 'i');
    const wordPrefixRegex = /^\s*[\w-]+:\s*/;
    if (prefixRegex.test(content)) {
      setContent(prev => prev.replace(prefixRegex, ''));
    } else if (wordPrefixRegex.test(content)) {
      setContent(prev => prev.replace(wordPrefixRegex, ''));
    }
  };

  const handleApplySuggestion = () => {
    if (!suggested) return;
    setSelectedCharacterId(suggested.char_id);
    stripCharacterPrefix(suggested.name);
  };

  const handlePromote = async () => {
    if (selectedCharacterId === '') {
      setError('Please select a character from the dropdown.');
      return;
    }

    const resolvedName =
      resolveCharacterName(Number(selectedCharacterId), characters) ||
      (suggested && suggested.char_id === Number(selectedCharacterId) ? suggested.name : null);

    if (!resolvedName) {
      setError('Selected character not found.');
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const authorPayload = {
        ...message.author,
        id: String(selectedCharacterId),
        name: resolvedName,
        nickname: resolvedName,
        isBot: true,
      };

      await api.resolveFlaggedMessage(backupId, message.message_id, {
        resolution: 'override',
        override_content: content.trim(),
        override_author: authorPayload,
      });
      onPromoted();
      onClose();
    } catch (err: unknown) {
      setError((err as Error).message || 'Failed to promote message.');
      setSaving(false);
    }
  };

  const modalTitle = `Override Message #${message.message_id}`;

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
        onClick={handlePromote}
        disabled={saving || selectedCharacterId === ''}
        loading={saving}
        icon={<Check size={14} />}
      >
        Confirm Override
      </Button>
    </div>
  );

  return (
    <Modal
      isOpen={Boolean(message)}
      onClose={onClose}
      title={modalTitle}
      size="lg"
      footer={footer}
    >
      <div className="flex-col gap-lg">
        {error && (
          <div className="banner-danger">
            <span className="text-md">{error}</span>
          </div>
        )}

        <p className="text-secondary text-md m-0">
          Edit the message&apos;s author or content to improve scene detection. This won&apos;t edit the original Discord message.
        </p>

        {/* 1-Click Character Suggestion Card */}
        {suggested && (
          <div
            style={{
              background: 'rgba(16, 185, 129, 0.12)',
              border: '1px solid rgba(16, 185, 129, 0.35)',
              borderRadius: '8px',
              padding: '0.75rem 1rem',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              flexWrap: 'wrap',
              gap: '0.5rem',
            }}
          >
            <div>
              <div style={{ fontSize: '0.85rem', color: 'var(--success)', fontWeight: 600 }}>
                Suggested Character: #{suggested.char_id} {suggested.name}
              </div>
              <div className="text-muted text-sm">
                {suggested.writer_name ? `Writer: ${suggested.writer_name} • ` : ''}Reason: {suggested.reason}
              </div>
            </div>
            <Button
              variant="success"
              size="xs"
              onClick={handleApplySuggestion}
            >
              Apply Suggestion
            </Button>
          </div>
        )}

        {/* Informative Original Author Display */}
        <div
          style={{
            background: 'var(--bg-tertiary)',
            padding: '0.5rem 0.85rem',
            borderRadius: '6px',
            border: '1px solid var(--border-color)',
            fontSize: '0.85rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '0.5rem',
          }}
        >
          <div>
            <span>Original Discord Author: </span>
            <strong className="text-primary">
              {message.author?.nickname || message.author?.name || 'Unknown Author'}
            </strong>
          </div>
          {message.author?.id && (
            <span className="text-secondary text-sm font-mono">
              Discord User ID: {message.author.id}
            </span>
          )}
        </div>

        {/* Known Characters Searchable Picker */}
        <div className="flex-col gap-xs">
          <label className="text-secondary text-sm font-semibold">
            Assign to Character {loadingCharacters && <span className="text-muted font-normal">(loading...)</span>}
          </label>
          <CharacterPicker
            characters={characters}
            selectedIds={selectedCharacterId !== '' ? [Number(selectedCharacterId)] : []}
            onChange={ids => setSelectedCharacterId(ids[0] ?? '')}
            multiple={false}
            includeVersions={true}
            variant="inline"
            fallbackOptions={fallbackOptions}
            loading={loadingCharacters}
            disabled={saving}
            maxListHeight={160}
            onSelectItem={item => stripCharacterPrefix(item.name)}
          />
        </div>

        {/* Message Content Textarea */}
        <div className="flex-col gap-xs">
          <label className="text-secondary text-sm font-semibold">
            Message Content
          </label>
          <textarea
            rows={4}
            value={content}
            onChange={e => setContent(e.target.value)}
            className="textarea"
          />
        </div>
      </div>
    </Modal>
  );
};
