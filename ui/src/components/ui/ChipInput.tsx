import React, { useState } from 'react';
import { FilterChip } from './Badge';

export interface ChipInputProps {
  values: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  label?: string;
  id?: string;
  disabled?: boolean;
  className?: string;
}

export const ChipInput: React.FC<ChipInputProps> = ({
  values,
  onChange,
  placeholder = 'Type and press Enter or comma...',
  label,
  id,
  disabled = false,
  className = '',
}) => {
  const [inputValue, setInputValue] = useState('');

  const addValues = (raw: string) => {
    const tokens = raw
      .split(',')
      .map(t => t.trim())
      .filter(t => t.length > 0);

    if (tokens.length === 0) return;

    const nextValues = [...values];
    let changed = false;

    for (const token of tokens) {
      if (!nextValues.includes(token)) {
        nextValues.push(token);
        changed = true;
      }
    }

    if (changed) {
      onChange(nextValues);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      if (inputValue.trim()) {
        addValues(inputValue);
        setInputValue('');
      }
    } else if (e.key === 'Backspace' && !inputValue && values.length > 0) {
      // Remove last tag when backspacing on empty input
      onChange(values.slice(0, -1));
    }
  };

  const handleBlur = () => {
    if (inputValue.trim()) {
      addValues(inputValue);
      setInputValue('');
    }
  };

  const handleRemove = (indexToRemove: number) => {
    onChange(values.filter((_, idx) => idx !== indexToRemove));
  };

  return (
    <div className={['form-group', className].filter(Boolean).join(' ')}>
      {label && (
        <label htmlFor={id} className="form-label">
          {label}
        </label>
      )}
      <div className="chip-input-container">
        {values.map((val, idx) => (
          <FilterChip
            key={`${val}-${idx}`}
            onRemove={disabled ? undefined : () => handleRemove(idx)}
          >
            {val}
          </FilterChip>
        ))}
        <input
          id={id}
          type="text"
          className="chip-input-field"
          value={inputValue}
          disabled={disabled}
          onChange={e => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onBlur={handleBlur}
          placeholder={values.length === 0 ? placeholder : ''}
        />
      </div>
    </div>
  );
};
