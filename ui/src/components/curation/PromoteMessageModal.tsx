import React, { useState, useEffect, useMemo } from 'react';
import { Check } from 'lucide-react';
import { Modal, Button } from '../ui';
import { api } from '../../api';
import type { FlaggedMessage, Character } from '../../types';
import { CharacterSearchPicker } from './CharacterSearchPicker';

interface PromoteMessageModalProps {
  backupId: string;
  message: FlaggedMessage | null;
  onClose: () => void;
  onPromoted: () => void;
}

export const PromoteMessageModal: React.FC<PromoteMessageModalProps> = ({
  backupId,
  message,
  onClose,
  onPromoted,
}) => {
  const suggested = message?.suggested_character;
  const [content, setContent] = useState(message?.content || '');
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loadingCharacters, setLoadingCharacters] = useState(false);
  const [selectedCharacterId, setSelectedCharacterId] = useState<number | ''>(
    suggested?.char_id ?? ''
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
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
  }, [backupId]);

  const characterOptions = useMemo(() => {
    const list: Array<{ id: number; name: string; writerName?: string | null }> = [];

    characters.forEach(char => {
      const mainName = char.name || char.names?.[0] || `Character #${char.id}`;
      const writer = char.writer_name || (Array.isArray(char.writer) ? char.writer[0] : null);
      list.push({ id: char.id, name: mainName, writerName: writer });

      const versions = char.versions || [];
      versions.forEach((v: { id: number; name?: string }) => {
        const vName = v.name || `Version #${v.id}`;
        list.push({
          id: v.id,
          name: `${vName} (${mainName})`,
          writerName: writer,
        });
      });
    });

    const uniqueMap = new Map<number, { id: number; name: string; writerName?: string | null }>();
    list.forEach(item => {
      if (!uniqueMap.has(item.id)) {
        uniqueMap.set(item.id, item);
      }
    });

    if (suggested && !uniqueMap.has(suggested.char_id)) {
      uniqueMap.set(suggested.char_id, {
        id: suggested.char_id,
        name: suggested.name,
        writerName: suggested.writer_name,
      });
    }

    return Array.from(uniqueMap.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [characters, suggested]);

  if (!message) return null;

  const handleApplySuggestion = () => {
    if (!suggested) return;
    setSelectedCharacterId(suggested.char_id);
    const escapedName = suggested.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const prefixRegex = new RegExp(`^\\s*${escapedName}\\s*:\\s*`, 'i');
    const wordPrefixRegex = /^\s*[\w-]+:\s*/;
    if (prefixRegex.test(content)) {
      setContent(prev => prev.replace(prefixRegex, ''));
    } else if (wordPrefixRegex.test(content)) {
      setContent(prev => prev.replace(wordPrefixRegex, ''));
    }
  };

  const handlePromote = async () => {
    if (selectedCharacterId === '') {
      setError('Please select a character from the dropdown.');
      return;
    }

    const chosenChar = characterOptions.find(c => c.id === Number(selectedCharacterId));
    if (!chosenChar) {
      setError('Selected character not found.');
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const authorPayload = {
        ...message.author,
        id: String(chosenChar.id),
        name: chosenChar.name,
        nickname: chosenChar.name,
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
      <div className="flex-col gap-md">
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
          <CharacterSearchPicker
            options={characterOptions}
            selectedId={selectedCharacterId}
            loading={loadingCharacters}
            disabled={saving}
            onSelect={opt => {
              setSelectedCharacterId(opt.id);
              const escapedName = opt.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
              const prefixRegex = new RegExp(`^\\s*${escapedName}\\s*:\\s*`, 'i');
              const wordPrefixRegex = /^\s*[\w-]+:\s*/;
              if (prefixRegex.test(content)) {
                setContent(prev => prev.replace(prefixRegex, ''));
              } else if (wordPrefixRegex.test(content)) {
                setContent(prev => prev.replace(wordPrefixRegex, ''));
              }
            }}
            onClear={() => setSelectedCharacterId('')}
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
