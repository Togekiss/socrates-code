import React, { useState, useEffect } from 'react';
import { GitMerge, ArrowUp, ArrowDown, AlertTriangle } from 'lucide-react';
import { Button } from '../ui';
import { api } from '../../api';
import type { SceneMergeNeighborsResponse } from '../../types';

interface SceneMergeSectionProps {
  backupId: string;
  sceneIdentifier: string | number;
  itemType: string;
  itemTypeCapital: string;
  disabled: boolean;
  onMerged: () => void;
  onError: (err: string) => void;
}

export const SceneMergeSection: React.FC<SceneMergeSectionProps> = ({
  backupId,
  sceneIdentifier,
  itemType,
  itemTypeCapital,
  disabled,
  onMerged,
  onError,
}) => {
  const [loading, setLoading] = useState(true);
  const [merging, setMerging] = useState(false);
  const [neighbors, setNeighbors] = useState<SceneMergeNeighborsResponse | null>(null);
  const [confirmDirection, setConfirmDirection] = useState<'prev' | 'next' | null>(null);
  const [confirmWarning, setConfirmWarning] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    api.getSceneMergeNeighbors(backupId, sceneIdentifier)
      .then(res => {
        if (mounted) setNeighbors(res);
      })
      .catch(err => {
        if (mounted) console.warn('Could not load merge neighbors:', err);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [backupId, sceneIdentifier]);

  const handleMergeClick = (direction: 'prev' | 'next') => {
    if (!neighbors) return;
    const info = direction === 'prev' ? neighbors.prev : neighbors.next;
    if (!info.exists || !info.can_merge) return;

    if (info.is_curator_split) {
      setConfirmDirection(direction);
      setConfirmWarning(
        info.warning ||
          `These ${itemType}s were previously separated by a curator (manual split or soft boundary). Merging will combine them and resolve the issue. Confirm to proceed.`
      );
      return;
    }
    executeMerge(direction, false);
  };

  const executeMerge = async (direction: 'prev' | 'next', force: boolean) => {
    setMerging(true);
    try {
      const res = await api.mergeScene(backupId, sceneIdentifier, direction, force);
      if (res.status === 'requires_confirmation') {
        setConfirmDirection(direction);
        setConfirmWarning(res.warning || `Confirmation required to merge ${itemType}s.`);
        setMerging(false);
        return;
      }
      onMerged();
    } catch (err: unknown) {
      onError(err instanceof Error ? err.message : `Failed to merge ${itemType}`);
      setMerging(false);
      setConfirmDirection(null);
    }
  };

  const isBusy = disabled || merging;
  const prevInfo = neighbors?.prev;
  const nextInfo = neighbors?.next;
  const canMergePrev = !isBusy && !loading && !!prevInfo?.exists && !!prevInfo?.can_merge;
  const canMergeNext = !isBusy && !loading && !!nextInfo?.exists && !!nextInfo?.can_merge;

  const prevTooltip = loading
    ? 'Checking neighbors...'
    : !prevInfo?.exists
    ? `This is the first ${itemType} in this channel.`
    : !prevInfo.can_merge
    ? prevInfo.disabled_reason || `Cannot merge with previous ${itemType}.`
    : `Merge with ${prevInfo.scene_key}${prevInfo.custom_name ? ` ("${prevInfo.custom_name}")` : ''}`;

  const nextTooltip = loading
    ? 'Checking neighbors...'
    : !nextInfo?.exists
    ? `This is the last ${itemType} in this channel.`
    : !nextInfo.can_merge
    ? nextInfo.disabled_reason || `Cannot merge with next ${itemType}.`
    : `Merge with ${nextInfo.scene_key}${nextInfo.custom_name ? ` ("${nextInfo.custom_name}")` : ''}`;

  return (
    <div
      style={{
        borderTop: '1px solid var(--border-color)',
        paddingTop: '0.9rem',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.65rem',
      }}
    >
      <div
        className="text-secondary text-sm font-semibold flex-row items-center gap-xs"
      >
        <GitMerge size={14} className="text-accent" />
        <span>Merge with Adjacent {itemTypeCapital}</span>
      </div>

      <div className="flex-row gap-sm">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => handleMergeClick('prev')}
          disabled={!canMergePrev}
          loading={merging && confirmDirection === 'prev'}
          icon={<ArrowUp size={13} />}
          title={prevTooltip}
          style={{ flex: 1 }}
        >
          Merge with previous {itemType}
        </Button>

        <Button
          variant="secondary"
          size="sm"
          onClick={() => handleMergeClick('next')}
          disabled={!canMergeNext}
          loading={merging && confirmDirection === 'next'}
          icon={<ArrowDown size={13} />}
          title={nextTooltip}
          style={{ flex: 1 }}
        >
          Merge with next {itemType}
        </Button>
      </div>

      {confirmDirection && (
        <div
          style={{
            background: 'rgba(234, 179, 8, 0.12)',
            border: '1px solid rgba(234, 179, 8, 0.4)',
            borderRadius: '6px',
            padding: '0.75rem',
            display: 'flex',
            flexDirection: 'column',
            gap: '0.5rem',
          }}
        >
          <div
            className="flex-row items-center gap-xs"
            style={{ color: '#eab308', fontSize: '0.82rem', fontWeight: 600 }}
          >
            <AlertTriangle size={15} />
            <span>Warning: Curator Decision</span>
          </div>
          <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', lineHeight: 1.45 }}>
            {confirmWarning ||
              `These ${itemType}s were separated by a curator. Merging will combine them and resolve the issue.`}
          </div>
          <div className="flex-row gap-xs justify-end mt-xs">
            <Button
              variant="ghost"
              size="xs"
              disabled={merging}
              onClick={() => {
                setConfirmDirection(null);
                setConfirmWarning(null);
              }}
            >
              Cancel
            </Button>
            <Button
              variant="warning"
              size="xs"
              disabled={merging}
              onClick={() => executeMerge(confirmDirection, true)}
              icon={<GitMerge size={13} />}
            >
              Confirm & Merge
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};
