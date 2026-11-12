import React from 'react';
import { X } from 'lucide-react';

interface BackupCategorySelectorProps {
  backupId: string;
  isKeepMode: boolean;
  toggleKeepMode: (keep: boolean) => void;
  categoriesList: string[];
  addCategory: (cat: string) => void;
  removeCategory: (cat: string) => void;
  chatroomCategoriesList: string[];
  addChatroomCategory: (cat: string) => void;
  removeChatroomCategory: (cat: string) => void;
  eventCategoriesList?: string[];
  addEventCategory?: (cat: string) => void;
  removeEventCategory?: (cat: string) => void;
  serverCategories: { id: string; name: string }[] | null;
  loadingCategories: boolean;
  categoriesError: string | null;
}

const selectStyle: React.CSSProperties = {
  flex: 1,
  padding: '0.45rem 0.65rem',
  background: 'var(--bg-tertiary)',
  border: '1px solid var(--border-color)',
  color: 'var(--text-primary)',
  borderRadius: 'var(--radius-sm)',
  fontSize: '0.875rem',
};

export const BackupCategorySelector: React.FC<BackupCategorySelectorProps> = ({
  backupId,
  isKeepMode,
  toggleKeepMode,
  categoriesList,
  addCategory,
  removeCategory,
  chatroomCategoriesList,
  addChatroomCategory,
  removeChatroomCategory,
  eventCategoriesList = [],
  addEventCategory,
  removeEventCategory,
  serverCategories,
  loadingCategories,
  categoriesError,
}) => {
  return (
    <>
      {/* Categories Filter Mode (Keep vs Ignore) */}
      <div>
        <label style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
          Categories Filter Mode
        </label>
        <div style={{ display: 'flex', gap: '1rem', marginBottom: '0.5rem' }}>
          <label style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <input
              type="radio"
              name={`catMode_${backupId}`}
              checked={!isKeepMode}
              onChange={() => toggleKeepMode(false)}
            />
            Ignore categories
          </label>
          <label style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <input
              type="radio"
              name={`catMode_${backupId}`}
              checked={isKeepMode}
              onChange={() => toggleKeepMode(true)}
            />
            Keep only categories
          </label>
        </div>

        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
          {loadingCategories ? (
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Loading categories...</div>
          ) : categoriesError ? (
            <div style={{ color: 'var(--danger)', fontSize: '0.85rem' }}>{categoriesError}</div>
          ) : serverCategories && serverCategories.length > 0 ? (
            <select
              onChange={e => {
                if (e.target.value) {
                  addCategory(e.target.value);
                  e.target.value = '';
                }
              }}
              defaultValue=""
              style={selectStyle}
            >
              <option value="" disabled>-- Select a category to filter --</option>
              {serverCategories.map(cat => (
                <option key={cat.id} value={cat.name} disabled={categoriesList.includes(cat.name)}>
                  {cat.name} {categoriesList.includes(cat.name) ? '(Added)' : ''}
                </option>
              ))}
            </select>
          ) : (
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No categories found</div>
          )}
        </div>

        {categoriesList.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.5rem' }}>
            {categoriesList.map((cat: string) => (
              <span
                key={cat}
                style={{
                  background: 'var(--bg-tertiary)',
                  padding: '0.25rem 0.5rem',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: '0.82rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.4rem',
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-primary)',
                }}
              >
                {cat}
                <X size={14} style={{ cursor: 'pointer' }} onClick={() => removeCategory(cat)} />
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Roleplayed Chatroom Categories */}
      <div style={{ marginTop: '0.5rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '0.25rem' }}>
          <label style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Chatroom Categories
          </label>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
            Indexed as 6-hour inactivity chat sessions
          </span>
        </div>

        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
          {serverCategories && serverCategories.length > 0 ? (
            <select
              onChange={e => {
                if (e.target.value) {
                  addChatroomCategory(e.target.value);
                  e.target.value = '';
                }
              }}
              defaultValue=""
              style={selectStyle}
            >
              <option value="" disabled>-- Select a chatroom category to add --</option>
              {serverCategories.map(cat => (
                <option key={cat.id} value={cat.name} disabled={chatroomCategoriesList.includes(cat.name)}>
                  {cat.name} {chatroomCategoriesList.includes(cat.name) ? '(Added)' : ''}
                </option>
              ))}
            </select>
          ) : (
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No categories available</div>
          )}
        </div>

        {chatroomCategoriesList.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.5rem' }}>
            {chatroomCategoriesList.map((cat: string) => (
              <span
                key={cat}
                style={{
                  background: 'var(--accent-subtle)',
                  border: '1px solid var(--accent-border)',
                  color: 'var(--accent-light)',
                  padding: '0.25rem 0.5rem',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: '0.82rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.4rem',
                }}
              >
                {cat}
                <X size={14} style={{ cursor: 'pointer' }} onClick={() => removeChatroomCategory(cat)} />
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Roleplayed Event Categories */}
      {addEventCategory && removeEventCategory && (
        <div style={{ marginTop: '0.5rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '0.25rem' }}>
            <label style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
              Event Categories
            </label>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              Merged into Events category &amp; indexed as server-wide events
            </span>
          </div>

          <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
            {serverCategories && serverCategories.length > 0 ? (
              <select
                onChange={e => {
                  if (e.target.value) {
                    addEventCategory(e.target.value);
                    e.target.value = '';
                  }
                }}
                defaultValue=""
                style={selectStyle}
              >
                <option value="" disabled>-- Select an event category to add --</option>
                {serverCategories.map(cat => (
                  <option key={cat.id} value={cat.name} disabled={eventCategoriesList.includes(cat.name)}>
                    {cat.name} {eventCategoriesList.includes(cat.name) ? '(Added)' : ''}
                  </option>
                ))}
              </select>
            ) : (
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No categories available</div>
            )}
          </div>

          {eventCategoriesList.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.5rem' }}>
              {eventCategoriesList.map((cat: string) => (
              <span
                key={cat}
                style={{
                  background: 'var(--badge-accent-bg, rgba(139, 92, 246, 0.15))',
                  border: '1px solid var(--badge-accent-border, rgba(139, 92, 246, 0.35))',
                  color: 'var(--accent-secondary)',
                  padding: '0.25rem 0.5rem',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: '0.82rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.4rem',
                }}
              >
                {cat}
                <X size={14} style={{ cursor: 'pointer' }} onClick={() => removeEventCategory(cat)} />
              </span>
              ))}
            </div>
          )}
        </div>
      )}
    </>
  );
};
