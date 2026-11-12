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
  onEdit?: (item: Scene | ChatSession) => void;
}

export const VirtualSceneList: React.FC<VirtualSceneListProps> = ({
  scenes,
  allCharacters,
  charactersFilter,
  setCharactersFilter,
  loadMore,
  hasMore,
  loading,
  mode = 'scenes',
  onEdit,
}) => {
  const parentRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: hasMore ? scenes.length + 1 : scenes.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => (mode === 'sessions' ? 140 : 120),
    overscan: 10,
  });

  const virtualItems = virtualizer.getVirtualItems();

  // Watch for scrolling near the bottom
  React.useEffect(() => {
    if (virtualItems.length === 0) return;
    const lastItem = virtualItems[virtualItems.length - 1];

    if (lastItem.index >= scenes.length - 1 && hasMore && !loading) {
      loadMore();
    }
  }, [virtualItems, hasMore, loading, scenes.length, loadMore]);

  if (scenes.length === 0 && !loading) {
    return (
      <div className="text-secondary text-center p-xl">
        {mode === 'sessions'
          ? 'No chat sessions match the current filters.'
          : 'No scenes match the current filters.'}
      </div>
    );
  }

  return (
    <div ref={parentRef} className="virtual-list-container">
      <div
        style={{
          height: `${virtualizer.getTotalSize()}px`,
          width: '100%',
          position: 'relative',
        }}
      >
        {virtualizer.getVirtualItems().map(virtualRow => {
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
                padding: '0 0 0.65rem 0',
              }}
            >
              {isLoaderRow ? (
                <div className="text-secondary text-center p-md">
                  {mode === 'sessions'
                    ? 'Loading more chat sessions...'
                    : 'Loading more scenes...'}
                </div>
              ) : mode === 'sessions' ? (
                <SessionCard
                  session={item as ChatSession}
                  allCharacters={allCharacters}
                  charactersFilter={charactersFilter}
                  setCharactersFilter={setCharactersFilter}
                  onEdit={onEdit}
                />
              ) : (
                <SceneCard
                  scene={item}
                  allCharacters={allCharacters}
                  charactersFilter={charactersFilter}
                  setCharactersFilter={setCharactersFilter}
                  onEdit={onEdit}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
