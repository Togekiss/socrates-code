import { useState } from 'react';
import { Sparkles, Check, CheckCheck, UserPlus, ChevronDown } from 'lucide-react';
import { PanelSurface, Button, Badge, ResponsiveText } from '../ui';
import type { WriterLinkSuggestion } from '../../types';
import { useResponsiveText } from '../../utils/responsiveText';

interface WriterLinkSuggestionsProps {
  suggestions: WriterLinkSuggestion[];
  linkingSuggestionId: number | null;
  unlinkedDiscordUsersCount?: number;
  acceptingAll?: boolean;
  creatingFromDiscordUsers?: boolean;
  disabled?: boolean;
  onAcceptSuggestion: (suggestion: WriterLinkSuggestion) => void;
  onAcceptAllSuggestions?: () => void;
  onCreateWritersFromDiscordUsers?: () => void;
}

const getConfidencePercent = (confidence: WriterLinkSuggestion['confidence']): number => {
  if (typeof confidence === 'number') {
    return Math.round(confidence <= 1 ? confidence * 100 : confidence);
  }
  if (confidence === 'high') return 95;
  if (confidence === 'medium') return 75;
  const parsed = parseFloat(String(confidence));
  if (!isNaN(parsed)) {
    return Math.round(parsed * (parsed <= 1 ? 100 : 1));
  }
  return 80;
};

export const WriterLinkSuggestions = ({
  suggestions,
  linkingSuggestionId,
  unlinkedDiscordUsersCount = 0,
  acceptingAll = false,
  creatingFromDiscordUsers = false,
  disabled = false,
  onAcceptSuggestion,
  onAcceptAllSuggestions,
  onCreateWritersFromDiscordUsers,
}: WriterLinkSuggestionsProps) => {
  const { isMobile } = useResponsiveText();
  const [collapsed, setCollapsed] = useState(isMobile);

  if (suggestions.length === 0 && unlinkedDiscordUsersCount === 0) {
    return null;
  }

  const batchBusy = acceptingAll || creatingFromDiscordUsers || linkingSuggestionId !== null;
  const headerTitle =
    suggestions.length > 0
      ? `Discord Link Suggestions (${suggestions.length})`
      : `Unlinked Discord Users (${unlinkedDiscordUsersCount})`;

  return (
    <PanelSurface
      className="flex-col gap-sm"
      style={{
        background: 'var(--bg-accent)',
        border: '1px solid var(--accent-border)',
        padding: isMobile && collapsed ? '0.4rem 0.8rem' : '0.8rem',
      }}
    >
      <div
        className="flex-row items-center justify-between gap-sm"
        style={{ cursor: 'pointer' }}
        onClick={() => setCollapsed(prev => !prev)}
      >
        <div className="flex-row items-center gap-xs" style={{ color: 'var(--accent-secondary)' }}>
          <Sparkles size={18} />
          <strong style={{ fontSize: '0.95rem' }}>{headerTitle}</strong>
        </div>

        <button
          type="button"
          className="collapsible-filter-toggle"
          onClick={e => {
            e.stopPropagation();
            setCollapsed(prev => !prev);
          }}
          aria-expanded={!collapsed}
          aria-label={collapsed ? 'Show Discord link suggestions' : 'Hide Discord link suggestions'}
        >
          <span className="hide-in-tablet">{collapsed ? 'Show' : 'Hide'}</span>
          <ChevronDown
            size={14}
            style={{
              transform: collapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
              transition: 'transform var(--transition-fast)',
            }}
          />
        </button>
      </div>

      {!collapsed && (
        <>
          <div className="flex-row items-center justify-between flex-wrap gap-sm">
            <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text-secondary)', flex: '1 1 260px' }}>
              {suggestions.length > 0
                ? 'Socrates detected matching Discord users for the following unlinked writers based on usernames and dialogue authorship:'
                : `${unlinkedDiscordUsersCount} seen Discord user${unlinkedDiscordUsersCount === 1 ? ' has' : 's have'} not been linked to any writer yet and ${unlinkedDiscordUsersCount === 1 ? 'has' : 'have'} no active link suggestion.`}
            </p>

            <div className="flex-row items-center flex-wrap gap-xs" style={{ flexShrink: 0 }}>
              {onAcceptAllSuggestions && suggestions.length > 0 && (
                <Button
                  variant="primary"
                  size="xs"
                  disabled={disabled || batchBusy}
                  title={disabled ? 'Curation edits are disabled while sync is in progress.' : undefined}
                  onClick={onAcceptAllSuggestions}
                  loading={acceptingAll}
                  icon={<CheckCheck size={12} />}
                >
                  Accept all suggestions ({suggestions.length})
                </Button>
              )}

              {onCreateWritersFromDiscordUsers && (
                <Button
                  variant="secondary"
                  size="xs"
                  disabled={disabled || batchBusy || unlinkedDiscordUsersCount === 0}
                  title={
                    disabled
                      ? 'Curation edits are disabled while sync is in progress.'
                      : unlinkedDiscordUsersCount === 0
                        ? 'All seen Discord users are already linked or have active suggestions.'
                        : 'Create writers for unlinked Discord users without active suggestions, using username as display name and global name / nickname as aliases.'
                  }
                  onClick={onCreateWritersFromDiscordUsers}
                  loading={creatingFromDiscordUsers}
                  icon={<UserPlus size={12} />}
                >
                  Create writers from Discord users
                  {unlinkedDiscordUsersCount > 0 ? ` (${unlinkedDiscordUsersCount})` : ''}
                </Button>
              )}
            </div>
          </div>

          {suggestions.length > 0 && (
            <div className="flex-col gap-xs" style={{ marginTop: '0.25rem' }}>
              {suggestions.map(s => {
                const writerId = s.writer_id ?? s.writer_pk ?? 0;
                const discordId = s.suggested_discord_id ?? s.suggested_discord_user_id ?? '';
                const confPct = getConfidencePercent(s.confidence);
                const username = s.suggested_username?.trim();
                const nickname = s.suggested_nickname?.trim();

                return (
                  <div
                    key={writerId || s.display_name}
                    className="panel-surface flex-row justify-between flex-wrap gap-sm"
                    style={{ padding: '0.6rem 0.9rem' }}
                  >
                    <div className="flex-col flex-1 gap-xs">
                      <div className="flex-row items-baseline gap-xs flex-wrap">
                        <strong style={{ marginRight: '0.2rem', color: 'var(--text-primary)' }}>{s.display_name}</strong>
                        <Badge variant="accent">
                          {confPct}% match
                        </Badge>
                        <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                          → Discord:{' '}
                          <span title={discordId ? `Snowflake ID: ${discordId}` : undefined}>
                            {username ? (
                              <code style={{ color: 'var(--accent-secondary)' }}>@{username}</code>
                            ) : null}
                            {nickname && nickname.toLowerCase() !== username?.toLowerCase() ? (
                              <span style={{ color: 'var(--text-primary)', marginLeft: username ? '0.35rem' : 0 }}>
                                ({nickname})
                              </span>
                            ) : null}
                            {!username && !nickname ? (
                              <code style={{ color: 'var(--accent-secondary)' }}>{discordId}</code>
                            ) : null}
                          </span>{' '}
                        </span>
                        <span className="form-hint hide-in-mobile">
                          ({s.reason})
                        </span>
                      </div>
                    </div>

                    <div className="flex-col items-end gap-xs" style={{ flexShrink: 0 }}>
                      <Button
                        variant="primary"
                        size="xs"
                        disabled={disabled || batchBusy}
                        title={disabled ? 'Curation edits are disabled while sync is in progress.' : undefined}
                        onClick={() => onAcceptSuggestion(s)}
                        loading={linkingSuggestionId === writerId}
                        icon={<Check size={12} />}
                      >
                        <ResponsiveText textKey="acceptDiscordLink" />
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </PanelSurface>
  );
};
