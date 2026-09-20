import React, { useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { CharacterCard } from './CharacterCard';

interface VirtualScrollListProps {
  characters: any[];
  onEdit: (char: any, parent?: any) => void;
  onAddTagFilter: (tag: string) => void;
  disableAccordion?: boolean;
}

export const VirtualScrollList: React.FC<VirtualScrollListProps> = ({ characters, onEdit, onAddTagFilter, disableAccordion }) => {
  const parentRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: characters.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 100,
    overscan: 5,
  });

  if (characters.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-secondary)' }}>
        No characters match the current filters.
      </div>
    );
  }

  return (
    <div
      ref={parentRef}
      style={{
        height: '600px',
        overflowY: 'auto',
        position: 'relative',
        borderRadius: '8px',
        background: 'rgba(0,0,0,0.2)'
      }}
    >
      <div
        style={{
          height: `${virtualizer.getTotalSize()}px`,
          width: '100%',
          position: 'relative',
        }}
      >
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const char = characters[virtualRow.index];
          return (
            <div
              key={virtualRow.key}
              data-index={virtualRow.index}
              ref={virtualizer.measureElement}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${virtualRow.start}px)`,
                padding: '0.5rem'
              }}
            >
              <CharacterCard 
                character={char} 
                onEdit={onEdit} 
                onAddTagFilter={onAddTagFilter} 
                disableAccordion={disableAccordion}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
};
