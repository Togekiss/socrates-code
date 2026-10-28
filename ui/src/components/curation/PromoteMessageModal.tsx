import React, { useState, useEffect, useMemo } from 'react';
import { X, Check, Loader2 } from 'lucide-react';
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

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(0, 0, 0, 0.75)',
        zIndex: 100,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backdropFilter: 'blur(4px)',
      }}
      onClick={e => {
        if (e.target === e.currentTarget && !saving) onClose();
      }}
    >
      <div
        style={{
          background: 'var(--bg-primary)',
          width: '720px',
          maxWidth: '92vw',
          borderRadius: '12px',
          border: '1px solid var(--border-color)',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.4)',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '0.75rem 0.5rem 0.5rem 1.5rem',
            borderBottom: '1px solid var(--border-color)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <h2 style={{ margin: 0, fontSize: '1.15rem', color: 'var(--text-primary)' }}>
            Override Message #{message.message_id}
          </h2>
          <button
            onClick={onClose}
            disabled={saving}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              display: 'flex',
            }}
          >
            <X size={20} />
          </button>
        </div>

        {/* Content */}
        <div style={{ padding: '0.75rem 1.25rem 1.25rem 1.25rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {error && (
            <div
              style={{
                background: 'rgba(239, 68, 68, 0.15)',
                border: '1px solid var(--danger)',
                color: 'var(--danger)',
                padding: '0.65rem 0.85rem',
                borderRadius: '6px',
                fontSize: '0.85rem',
              }}
            >
              {error}
            </div>
          )}

          <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            Edit the message's author or content to improve scene detection. This won't edit the original Discord message.
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
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                  {suggested.writer_name ? `Writer: ${suggested.writer_name} • ` : ''}Reason: {suggested.reason}
                </div>
              </div>
              <button
                type="button"
                onClick={handleApplySuggestion}
                style={{
                  padding: '0.35rem 0.75rem',
                  background: 'var(--success)',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '6px',
                  fontSize: '0.8rem',
                  fontWeight: 600,
                  cursor: 'pointer',
                  whiteSpace: 'nowrap',
                }}
              >
                Apply Suggestion
              </button>
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
              <strong style={{ color: 'var(--text-primary)' }}>
                {message.author?.nickname || message.author?.name || 'Unknown Author'}
              </strong>
            </div>
            {message.author?.id && (
              <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', fontFamily: 'monospace' }}>
                Discord User ID: {message.author.id}
              </span>
            )}
          </div>

          {/* Known Characters Searchable Picker */}
          <div>
            <label style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontWeight: 600, display: 'block', marginBottom: '0.35rem' }}>
              Assign to Character {loadingCharacters && <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}>(loading...)</span>}
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
          <div>
            <label style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontWeight: 600, display: 'block', marginBottom: '0.35rem' }}>
              Message Content
            </label>
            <textarea
              rows={4}
              value={content}
              onChange={e => setContent(e.target.value)}
              style={{
                width: '100%',
                padding: '0.65rem 0.75rem',
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                borderRadius: '6px',
                color: 'white',
                fontSize: '0.9rem',
                resize: 'vertical',
                lineHeight: 1.5,
              }}
            />
          </div>
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '1rem 1.25rem',
            borderTop: '1px solid var(--border-color)',
            display: 'flex',
            justifyContent: 'flex-end',
            gap: '0.5rem',
            background: 'var(--bg-secondary)',
            borderRadius: '0 0 12px 12px',
          }}
        >
          <button
            onClick={onClose}
            disabled={saving}
            style={{
              padding: '0.45rem 1rem',
              background: 'transparent',
              border: '1px solid var(--border-color)',
              color: 'var(--text-primary)',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '0.85rem',
            }}
          >
            Cancel
          </button>
          <button
            onClick={handlePromote}
            disabled={saving || selectedCharacterId === ''}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.4rem',
              padding: '0.45rem 1.25rem',
              background: 'var(--accent-primary)',
              border: 'none',
              color: '#fff',
              borderRadius: '6px',
              fontWeight: 600,
              cursor: saving || selectedCharacterId === '' ? 'not-allowed' : 'pointer',
              opacity: selectedCharacterId === '' ? 0.6 : 1,
              fontSize: '0.85rem',
            }}
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
            Confirm Override
          </button>
        </div>
      </div>
    </div>
  );
};
