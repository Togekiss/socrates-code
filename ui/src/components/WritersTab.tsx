import { useState, useEffect, useCallback } from 'react';
import {
  UserCheck,
  Plus,
  Search,
  Sparkles,
  Check,
  AlertCircle,
  Users,
  Loader2,
} from 'lucide-react';
import { api } from '../api';
import { WriterEditModal } from './curation/WriterEditModal';
import { AssignWriterModal } from './curation/AssignWriterModal';
import { WriterCard } from './curation/WriterCard';
import { UnassignedCharacterCard } from './curation/UnassignedCharacterCard';
import type {
  UnassignedCharacter,
  WriterDetailed,
  WriterLinkSuggestion,
} from '../types';

interface WritersTabProps {
  backupId: string;
  onRefreshSummary?: () => void;
}

export const WritersTab = ({ backupId, onRefreshSummary }: WritersTabProps) => {
  const [activeSection, setActiveSection] = useState<'writers' | 'unassigned'>('writers');
  const [writers, setWriters] = useState<WriterDetailed[]>([]);
  const [unassignedChars, setUnassignedChars] = useState<UnassignedCharacter[]>([]);
  const [suggestions, setSuggestions] = useState<WriterLinkSuggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');

  // Modals state
  const [editingWriter, setEditingWriter] = useState<WriterDetailed | null>(null);
  const [isCreatingWriter, setIsCreatingWriter] = useState(false);
  const [assigningChar, setAssigningChar] = useState<UnassignedCharacter | null>(null);
  const [linkingSuggestionId, setLinkingSuggestionId] = useState<number | null>(null);

  const fetchData = useCallback(() => {
    if (!backupId) return;
    setLoading(true);
    Promise.all([
      api.getWritersDetailed(backupId),
      api.getUnassignedCharacters(backupId),
      api.getWriterLinkSuggestions(backupId).catch(() => []),
    ])
      .then(([wData, uData, sData]) => {
        setWriters(Array.isArray(wData) ? wData : []);
        setUnassignedChars(Array.isArray(uData) ? uData : []);
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

  const filteredUnassigned = unassignedChars.filter(c => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    const hasNameMatch = (c.name || c.names?.[0] || '').toLowerCase().includes(q);
    const hasIdMatch = String(c.id).includes(q);
    return hasNameMatch || hasIdMatch;
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header Bar */}
      <div
        className="glass-panel"
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '1rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div
            style={{
              width: '40px',
              height: '40px',
              borderRadius: '8px',
              background: 'rgba(109, 40, 217, 0.15)',
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
              Writers & Attribution
            </h2>
            <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text-muted)' }}>
              Manage writer profiles, Discord snowflake links, and character assignments
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
            <Search size={14} style={{ position: 'absolute', left: '0.75rem', color: 'var(--text-muted)' }} />
            <input
              type="text"
              placeholder={activeSection === 'writers' ? 'Search writers...' : 'Search unassigned...'}
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{
                padding: '0.45rem 0.75rem 0.45rem 2.2rem',
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border-color)',
                borderRadius: '6px',
                color: 'white',
                fontSize: '0.85rem',
                width: '200px',
              }}
            />
          </div>

          <button
            onClick={() => setIsCreatingWriter(true)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.4rem',
              padding: '0.5rem 1rem',
              background: 'var(--accent-primary)',
              color: '#fff',
              border: 'none',
              borderRadius: '6px',
              fontWeight: 600,
              fontSize: '0.85rem',
              cursor: 'pointer',
            }}
          >
            <Plus size={16} /> New Writer
          </button>
        </div>
      </div>

      {/* Heuristic Link Suggestions Banner */}
      {suggestions.length > 0 && activeSection === 'writers' && (
        <div
          style={{
            background: 'rgba(109, 40, 217, 0.12)',
            border: '1px solid rgba(139, 92, 246, 0.35)',
            borderRadius: '10px',
            padding: '1rem 1.25rem',
            display: 'flex',
            flexDirection: 'column',
            gap: '0.75rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--accent-secondary)' }}>
            <Sparkles size={18} />
            <strong style={{ fontSize: '0.95rem' }}>
              Discord Link Suggestions ({suggestions.length})
            </strong>
          </div>
          <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            Socrates detected matching Discord users for the following unlinked writers based on dialogue authorship:
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginTop: '0.25rem' }}>
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
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    background: 'var(--bg-secondary)',
                    padding: '0.6rem 0.9rem',
                    borderRadius: '6px',
                    border: '1px solid var(--border-color)',
                  }}
                >
                  <div>
                    <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{s.display_name}</span>
                    <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem', marginLeft: '0.5rem' }}>
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
                      ({confPct}% match: {s.reason})
                    </span>
                  </div>
                  <button
                    onClick={() => handleAcceptSuggestion(s)}
                    disabled={linkingSuggestionId === writerId}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.35rem',
                      padding: '0.35rem 0.75rem',
                      background: 'var(--accent-primary)',
                      color: '#fff',
                      border: 'none',
                      borderRadius: '4px',
                      fontSize: '0.8rem',
                      fontWeight: 600,
                      cursor: linkingSuggestionId === writerId ? 'not-allowed' : 'pointer',
                    }}
                  >
                    {linkingSuggestionId === writerId ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <Check size={12} />
                    )}
                    Accept Link
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Sub-Navigation: Writers Roster vs Unassigned Characters */}
      <div style={{ display: 'flex', gap: '0.5rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '0.5rem' }}>
        <button
          onClick={() => setActiveSection('writers')}
          style={{
            padding: '0.45rem 1rem',
            background: activeSection === 'writers' ? 'var(--bg-tertiary)' : 'transparent',
            border: 'none',
            borderBottom: activeSection === 'writers' ? '2px solid var(--accent-primary)' : '2px solid transparent',
            color: activeSection === 'writers' ? 'var(--text-primary)' : 'var(--text-secondary)',
            fontWeight: activeSection === 'writers' ? 600 : 500,
            fontSize: '0.9rem',
            cursor: 'pointer',
            borderRadius: '6px 6px 0 0',
          }}
        >
          Writers Roster ({writers.length})
        </button>
        <button
          onClick={() => setActiveSection('unassigned')}
          style={{
            padding: '0.45rem 1rem',
            background: activeSection === 'unassigned' ? 'var(--bg-tertiary)' : 'transparent',
            border: 'none',
            borderBottom: activeSection === 'unassigned' ? '2px solid var(--accent-primary)' : '2px solid transparent',
            color: activeSection === 'unassigned' ? 'var(--text-primary)' : 'var(--text-secondary)',
            fontWeight: activeSection === 'unassigned' ? 600 : 500,
            fontSize: '0.9rem',
            cursor: 'pointer',
            borderRadius: '6px 6px 0 0',
          }}
        >
          Unassigned Characters ({unassignedChars.length})
        </button>
      </div>

      {/* Body Content */}
      {loading ? (
        <div className="glass-panel" style={{ textAlign: 'center', padding: '3rem' }}>
          <Loader2 size={32} className="animate-spin" style={{ color: 'var(--accent-secondary)', margin: '0 auto 1rem auto' }} />
          <p style={{ color: 'var(--text-secondary)' }}>Loading writers data...</p>
        </div>
      ) : activeSection === 'writers' ? (
        filteredWriters.length === 0 ? (
          <div className="glass-panel" style={{ textAlign: 'center', padding: '3rem' }}>
            <Users size={36} style={{ color: 'var(--text-muted)', marginBottom: '0.5rem', opacity: 0.5 }} />
            <p style={{ color: 'var(--text-secondary)' }}>No writers found.</p>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '1rem' }}>
            {filteredWriters.map(writer => (
              <WriterCard
                key={writer.id}
                writer={writer}
                onEdit={setEditingWriter}
              />
            ))}
          </div>
        )
      ) : (
        /* Unassigned Characters Queue */
        filteredUnassigned.length === 0 ? (
          <div className="glass-panel" style={{ textAlign: 'center', padding: '3rem' }}>
            <UserCheck size={36} style={{ color: 'var(--success)', marginBottom: '0.5rem' }} />
            <h3 style={{ margin: '0 0 0.5rem 0', color: 'var(--text-primary)' }}>
              All characters are assigned!
            </h3>
            <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
              Every character in this backup has a designated writer.
            </p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            <div
              style={{
                background: 'rgba(245, 158, 11, 0.08)',
                border: '1px solid rgba(245, 158, 11, 0.25)',
                borderRadius: '8px',
                padding: '0.85rem 1.25rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                color: 'var(--warning)',
                fontSize: '0.85rem',
              }}
            >
              <AlertCircle size={16} />
              <span>
                These characters do not belong to any writer yet. Assigning a writer associates scene statistics and credits.
              </span>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '0.75rem' }}>
              {filteredUnassigned.map(char => (
                <UnassignedCharacterCard
                  key={char.id}
                  char={char}
                  onAssign={setAssigningChar}
                />
              ))}
            </div>
          </div>
        )
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

      {/* Assign Writer Modal */}
      {assigningChar && (
        <AssignWriterModal
          backupId={backupId}
          character={assigningChar}
          writers={writers}
          onClose={() => setAssigningChar(null)}
          onAssigned={fetchData}
        />
      )}
    </div>
  );
};
