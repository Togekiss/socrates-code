import React, { useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { CharacterCard } from './CharacterCard';
import { GroupCard } from './GroupCard';
import type { Character, CharacterGroup } from '../../types';

export type VirtualListItem =
  | { _isGroup: true; id: string | number; group: CharacterGroup; members: Character[] }
  | ({ _isGroup?: false; id: number; character?: Character } & Partial<Character>);

interface VirtualScrollListProps {
  items: VirtualListItem[];
  onEdit: (char: Character, parent?: Character) => void;
  onEditGroup?: (group: CharacterGroup) => void;
  onAddTagFilter: (tag: string) => void;
  onAssignWriter?: (char: Character) => void;
  disableAccordion?: boolean;
}

export const VirtualScrollList: React.FC<VirtualScrollListProps> = ({
  items,
  onEdit,
  onEditGroup,
  onAddTagFilter,
  onAssignWriter,
  disableAccordion,
}) => {
  const parentRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: index => (items[index]?._isGroup ? 240 : 120),
    getItemKey: index => items[index]?.id ?? index,
    overscan: 5,
  });

  if (items.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-secondary)' }}>
        No characters or groups match the current filters.
      </div>
    );
  }

  return (
    <div
      ref={parentRef}
      className="virtual-list-container"
    >
      <div
        style={{
          height: `${virtualizer.getTotalSize()}px`,
          width: '100%',
          position: 'relative',
        }}
      >
        {virtualizer.getVirtualItems().map(virtualRow => {
          const item = items[virtualRow.index];
          if (!item) return null;

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
              {item._isGroup ? (
                <GroupCard
                  group={item.group}
                  members={item.members || []}
                  onEditGroup={onEditGroup || (() => {})}
                  onEditCharacter={onEdit}
                  onAddTagFilter={onAddTagFilter}
                  onAssignWriter={onAssignWriter}
                  disableAccordion={disableAccordion}
                />
              ) : (
                <CharacterCard
                  character={item.character || (item as unknown as Character)}
                  onEdit={onEdit}
                  onAddTagFilter={onAddTagFilter}
                  onAssignWriter={onAssignWriter}
                  disableAccordion={disableAccordion}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
