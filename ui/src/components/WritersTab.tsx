import { useState, useEffect, useCallback } from 'react';
import {
  UserCheck,
  Plus,
  Search,
  Sparkles,
  Check,
  Users,
  Loader2,
} from 'lucide-react';
import { api } from '../api';
import { WriterEditModal } from './curation/WriterEditModal';
import { WriterCard } from './curation/WriterCard';
import { PanelSurface, Button, Badge } from './ui';
import type { WriterDetailed, WriterLinkSuggestion } from '../types';

interface WritersTabProps {
  backupId: string;
  onRefreshSummary?: () => void;
}

export const WritersTab = ({ backupId, onRefreshSummary }: WritersTabProps) => {
  const [writers, setWriters] = useState<WriterDetailed[]>([]);
  const [suggestions, setSuggestions] = useState<WriterLinkSuggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');

  // Modals state
  const [editingWriter, setEditingWriter] = useState<WriterDetailed | null>(null);
  const [isCreatingWriter, setIsCreatingWriter] = useState(false);
  const [linkingSuggestionId, setLinkingSuggestionId] = useState<number | null>(null);

  const fetchData = useCallback(() => {
    if (!backupId) return;
    setLoading(true);
    Promise.all([
      api.getWritersDetailed(backupId),
      api.getWriterLinkSuggestions(backupId).catch(() => []),
    ])
      .then(([wData, sData]) => {
        setWriters(Array.isArray(wData) ? wData : []);
        setSuggestions(Array.isArray(sData) ? sData : []);
      })
      .catch(console.error)
      .finally(() => {
        setLoading(false);
        if (onRefreshSummary) onRefreshSummary();
      });
  }, [backupId, onRefreshSummary]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleAcceptSuggestion = async (sugg: WriterLinkSuggestion) => {
    const writerId = sugg.writer_id ?? sugg.writer_pk;
    const discordId = sugg.suggested_discord_id ?? sugg.suggested_discord_user_id;
    if (!writerId || !discordId) return;

    setLinkingSuggestionId(writerId);
    try {
      await api.updateWriter(backupId, writerId, {
        discord_user_id: discordId,
      });
      fetchData();
    } catch (err) {
      console.error('Failed to link suggestion:', err);
    } finally {
      setLinkingSuggestionId(null);
    }
  };

  const filteredWriters = writers.filter(w => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    const hasNameMatch = w.display_name.toLowerCase().includes(q);
    const hasAliasMatch = w.aliases?.some(a => a.toLowerCase().includes(q));
    const hasCharMatch = w.characters?.some(c => c.name.toLowerCase().includes(q));
    return hasNameMatch || hasAliasMatch || hasCharMatch;
  });

  return (
    <div className="flex-col gap-lg">
      {/* Header Bar */}
      <PanelSurface className="flex-row items-center justify-between flex-wrap gap-md">
        <div className="flex-row items-center gap-sm">
          <div
            style={{
              width: '40px',
              height: '40px',
              borderRadius: 'var(--radius-sm)',
              background: 'var(--accent-subtle)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--accent-secondary)',
            }}
          >
            <UserCheck size={22} />
          </div>
          <div>
            <h2 style={{ margin: 0, fontSize: '1.25rem', color: 'var(--text-primary)' }}>
              Writers &amp; Attribution
            </h2>
            <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text-muted)' }}>
              Manage writer profiles, Discord snowflake links, and character assignments
            </p>
          </div>
        </div>

        <div className="flex-row items-center gap-sm flex-wrap">
          <div className="search-input-wrapper" style={{ width: '220px' }}>
            <Search size={14} />
            <input
              type="text"
              className="input"
              placeholder="Search writers..."
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>

          <Button
            variant="primary"
            size="sm"
            onClick={() => setIsCreatingWriter(true)}
            icon={<Plus size={15} />}
          >
            New Writer
          </Button>
        </div>
      </PanelSurface>

      {/* Discord Link Suggestions Banner */}
      {suggestions.length > 0 && (
        <PanelSurface
          className="flex-col gap-sm"
          style={{
            background: 'rgba(109, 40, 217, 0.12)',
            border: '1px solid rgba(139, 92, 246, 0.35)',
          }}
        >
          <div className="flex-row items-center gap-xs" style={{ color: 'var(--accent-secondary)' }}>
            <Sparkles size={18} />
            <strong style={{ fontSize: '0.95rem' }}>
              Discord Link Suggestions ({suggestions.length})
            </strong>
          </div>
          <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            Socrates detected matching Discord users for the following unlinked writers based on dialogue authorship:
          </p>

          <div className="flex-col gap-xs" style={{ marginTop: '0.25rem' }}>
            {suggestions.map(s => {
              const writerId = s.writer_id ?? s.writer_pk ?? 0;
              const discordId = s.suggested_discord_id ?? s.suggested_discord_user_id ?? '';
              const confPct =
                typeof s.confidence === 'number'
                  ? Math.round(s.confidence <= 1 ? s.confidence * 100 : s.confidence)
                  : s.confidence === 'high'
                  ? 95
                  : s.confidence === 'medium'
                  ? 75
                  : !isNaN(parseFloat(String(s.confidence)))
                  ? Math.round(
                      parseFloat(String(s.confidence)) *
                        (parseFloat(String(s.confidence)) <= 1 ? 100 : 1)
                    )
                  : 80;

              const username = s.suggested_username?.trim();
              const nickname = s.suggested_nickname?.trim();

              return (
                <div
                  key={writerId || s.display_name}
                  className="panel-surface flex-row items-center justify-between flex-wrap gap-sm"
                  style={{ padding: '0.6rem 0.9rem' }}
                >
                  <div className="flex-row items-center gap-xs flex-wrap">
                    <strong style={{ color: 'var(--text-primary)' }}>{s.display_name}</strong>
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
                      <Badge variant="accent">
                        {confPct}% match
                      </Badge>
                      <span className="form-hint" style={{ marginLeft: '0.35rem' }}>
                        ({s.reason})
                      </span>
                    </span>
                  </div>

                  <Button
                    variant="primary"
                    size="xs"
                    onClick={() => handleAcceptSuggestion(s)}
                    loading={linkingSuggestionId === writerId}
                    icon={<Check size={12} />}
                  >
                    Accept Link
                  </Button>
                </div>
              );
            })}
          </div>
        </PanelSurface>
      )}

      {/* Writers Roster Grid */}
      {loading ? (
        <PanelSurface style={{ textAlign: 'center', padding: '3rem' }}>
          <Loader2 size={32} className="animate-spin" style={{ color: 'var(--accent-secondary)', margin: '0 auto 1rem auto' }} />
          <p style={{ color: 'var(--text-secondary)' }}>Loading writers data...</p>
        </PanelSurface>
      ) : filteredWriters.length === 0 ? (
        <div className="empty-state">
          <Users size={40} className="empty-state-icon" />
          <h3 className="empty-state-title">No writers found</h3>
          <p className="empty-state-desc">
            {search ? `No writers match your search "${search}".` : 'No writer profiles exist yet.'}
          </p>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setIsCreatingWriter(true)}
            icon={<Plus size={14} />}
          >
            Create Writer
          </Button>
        </div>
      ) : (
        <div className="writers-grid">
          {filteredWriters.map(writer => (
            <WriterCard
              key={writer.id}
              writer={writer}
              onEdit={setEditingWriter}
            />
          ))}
        </div>
      )}

      {/* Writer Edit / Create Modal */}
      {(isCreatingWriter || editingWriter) && (
        <WriterEditModal
          backupId={backupId}
          writer={editingWriter}
          onClose={() => {
            setIsCreatingWriter(false);
            setEditingWriter(null);
          }}
          onSaved={fetchData}
        />
      )}
    </div>
  );
};
