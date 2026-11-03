import React, { useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { SceneCard } from './SceneCard';
import { SessionCard } from './SessionCard';
import type { Character, ChatSession, Scene } from '../../types';

interface VirtualSceneListProps {
  scenes: (Scene | ChatSession)[];
  allCharacters: Character[];
  charactersFilter: number[];
  setCharactersFilter: (filter: number[]) => void;
  loadMore: () => void;
  hasMore: boolean;
  loading: boolean;
  mode?: 'scenes' | 'sessions';
}

export const VirtualSceneList: React.FC<VirtualSceneListProps> = ({ 
  scenes, allCharacters, charactersFilter, setCharactersFilter, loadMore, hasMore, loading, mode = 'scenes'
}) => {
  const parentRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: hasMore ? scenes.length + 1 : scenes.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => (mode === 'sessions' ? 140 : 120),
    overscan: 10,
  });

  // Watch for scrolling near the bottom
  React.useEffect(() => {
    const [lastItem] = [...virtualizer.getVirtualItems()].reverse();
    if (!lastItem) return;
    
    if (lastItem.index >= scenes.length - 1 && hasMore && !loading) {
      loadMore();
    }
  }, [virtualizer.getVirtualItems(), hasMore, loading, scenes.length, loadMore]);

  if (scenes.length === 0 && !loading) {
    return (
      <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-secondary)' }}>
        {mode === 'sessions' ? 'No chat sessions match the current filters.' : 'No scenes match the current filters.'}
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
          const isLoaderRow = virtualRow.index > scenes.length - 1;
          const item = scenes[virtualRow.index];

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
                padding: '0.25rem 0'
              }}
            >
              {isLoaderRow ? (
                <div style={{ padding: '1rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
                  {mode === 'sessions' ? 'Loading more chat sessions...' : 'Loading more scenes...'}
                </div>
              ) : mode === 'sessions' ? (
                <SessionCard
                  session={item as ChatSession}
                  allCharacters={allCharacters}
                  charactersFilter={charactersFilter}
                  setCharactersFilter={setCharactersFilter}
                />
              ) : (
                <SceneCard 
                  scene={item} 
                  allCharacters={allCharacters}
                  charactersFilter={charactersFilter}
                  setCharactersFilter={setCharactersFilter}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
