import React from 'react';
import { Plus } from 'lucide-react';
import {
  Button,
  DataCard,
  FilterChip,
  type BadgeVariant,
  type DataCardAccent,
} from '../ui';

export interface RbacSelectOption {
  id: string;
  label: string;
}

export interface RbacBucketCardProps {
  title: string;
  description: string;
  icon?: React.ReactNode;
  accent?: DataCardAccent;
  chipVariant?: BadgeVariant;
  chipIcon?: React.ReactNode;
  selectedIds: string[];
  options: RbacSelectOption[];
  getDisplayLabel: (id: string) => string;
  selectPlaceholder: string;
  selectAriaLabel: string;
  emptySelectText?: string;
  manualInputPlaceholder: string;
  manualInputValue: string;
  onManualInputChange: (value: string) => void;
  onAddId: (id: string) => void;
  onRemoveId: (id: string) => void;
  emptyText: string;
  removeAriaPrefix: string;
}

export const RbacBucketCard: React.FC<RbacBucketCardProps> = ({
  title,
  description,
  icon,
  accent,
  chipVariant = 'accent',
  chipIcon,
  selectedIds,
  options,
  getDisplayLabel,
  selectPlaceholder,
  selectAriaLabel,
  emptySelectText,
  manualInputPlaceholder,
  manualInputValue,
  onManualInputChange,
  onAddId,
  onRemoveId,
  emptyText,
  removeAriaPrefix,
}) => {
  return (
    <DataCard accent={accent} className="flex-col gap-sm">
      <div className="flex-row items-start gap-sm">
        {icon && <span className="section-header-icon text-secondary">{icon}</span>}
        <div>
          <h4 className="m-0 text-md">{title}</h4>
          <p className="m-0 text-sm text-muted">{description}</p>
        </div>
      </div>

      <div className="rbac-input-row">
        {options.length > 0 || emptySelectText ? (
          <select
            aria-label={selectAriaLabel}
            className="select rbac-select"
            value=""
            disabled={options.length === 0}
            onChange={e => {
              if (e.target.value) {
                onAddId(e.target.value);
              }
            }}
          >
            <option value="">
              {options.length > 0 ? selectPlaceholder : emptySelectText || selectPlaceholder}
            </option>
            {options.map(opt => (
              <option key={opt.id} value={opt.id}>
                {opt.label}
              </option>
            ))}
          </select>
        ) : null}

        <div className="rbac-manual-group">
          <input
            type="text"
            className="input flex-1"
            placeholder={manualInputPlaceholder}
            value={manualInputValue}
            onChange={e => onManualInputChange(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                e.preventDefault();
                onAddId(manualInputValue);
              }
            }}
          />
          <Button
            variant="secondary"
            size="sm"
            icon={<Plus size={14} />}
            onClick={() => onAddId(manualInputValue)}
          >
            Add ID
          </Button>
        </div>
      </div>

      {selectedIds.length > 0 ? (
        <div className="rbac-chips-row">
          {selectedIds.map(id => (
            <FilterChip
              key={id}
              active
              variant={chipVariant}
              icon={chipIcon}
              onRemove={() => onRemoveId(id)}
              title={`${removeAriaPrefix} ${id}`}
            >
              <span className="font-mono">{getDisplayLabel(id)}</span>
            </FilterChip>
          ))}
        </div>
      ) : (
        <p className="rbac-empty-text">{emptyText}</p>
      )}
    </DataCard>
  );
};
