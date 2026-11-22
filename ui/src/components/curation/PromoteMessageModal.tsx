import React, { useState, useEffect, useMemo, useRef } from 'react';
import { Check, Loader2, AlertTriangle } from 'lucide-react';
import { Modal, Button, Badge, CharacterPicker } from '../ui';
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
  const [baselineContent, setBaselineContent] = useState(message?.content || '');
  const [hydratingContent, setHydratingContent] = useState(false);
  const [isHydrated, setIsHydrated] = useState(false);
  const [isDeletedOnDiscord, setIsDeletedOnDiscord] = useState(Boolean(message?.is_deleted));
  const userEditedRef = useRef(false);
  const [characters, setCharacters] = useState<Character[]>(allCharacters ?? []);
  const [loadingCharacters, setLoadingCharacters] = useState(false);
  const [selectedCharacterId, setSelectedCharacterId] = useState<number | ''>(
    suggested?.char_id ?? ''
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!message) return;
    const initial = message.content || '';
    setContent(initial);
    setBaselineContent(initial);
    setIsDeletedOnDiscord(Boolean(message.is_deleted));
    setIsHydrated(!message.is_excerpt_truncated);
    userEditedRef.current = false;

    if (!backupId || !message.is_excerpt_truncated) {
      setHydratingContent(false);
      return;
    }

    let cancelled = false;
    setHydratingContent(true);
    api
      .getFlaggedMessageFullContent(backupId, message.message_id)
      .then(res => {
        if (cancelled) return;
        if (res.is_deleted) {
          setIsDeletedOnDiscord(true);
        }
        if (res.hydrated) {
          setIsHydrated(true);
          setBaselineContent(res.content);
          if (!userEditedRef.current) {
            setContent(res.content);
          }
        }
      })
      .catch(err => {
        if (!cancelled) {
          console.warn('Failed to hydrate full message content:', err);
        }
      })
      .finally(() => {
        if (!cancelled) setHydratingContent(false);
      });

    return () => {
      cancelled = true;
    };
  }, [backupId, message]);

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
      userEditedRef.current = true;
      setContent(prev => prev.replace(prefixRegex, ''));
    } else if (wordPrefixRegex.test(content)) {
      userEditedRef.current = true;
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

      const isContentEdited = content.trim() !== baselineContent.trim();
      await api.resolveFlaggedMessage(backupId, message.message_id, {
        resolution: 'override',
        override_content: isContentEdited ? content.trim() : null,
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
          <div className="flex-row items-center justify-between flex-wrap gap-xs">
            <label className="text-secondary text-sm font-semibold">
              Message Content
            </label>
            <div className="flex-row items-center gap-xs">
              {hydratingContent && (
                <span className="flex-row items-center gap-xs text-accent text-sm">
                  <Loader2 size={13} className="animate-spin" />
                  Loading full message...
                </span>
              )}
              {isDeletedOnDiscord && (
                <Badge variant="danger" className="text-sm font-semibold">
                  <AlertTriangle size={12} />
                  Deleted on Discord
                </Badge>
              )}
            </div>
          </div>
          {isDeletedOnDiscord && (
            <div className="banner-warning" style={{ padding: '0.4rem 0.65rem', fontSize: '0.8rem' }}>
              This message or channel was deleted on Discord. {message.is_excerpt_truncated && !isHydrated ? 'Showing stored 250-character excerpt.' : ''}
            </div>
          )}
          {!isDeletedOnDiscord && message.is_excerpt_truncated && !hydratingContent && !isHydrated && (
            <div className="banner-info" style={{ padding: '0.4rem 0.65rem', fontSize: '0.8rem' }}>
              Full message could not be fetched; showing stored excerpt. Leave content unchanged to override author only.
            </div>
          )}
          <textarea
            rows={4}
            value={content}
            disabled={hydratingContent || saving}
            onChange={e => {
              userEditedRef.current = true;
              setContent(e.target.value);
            }}
            className="textarea"
          />
        </div>
      </div>
    </Modal>
  );
};
