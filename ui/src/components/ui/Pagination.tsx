import React from 'react';
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react';
import { Button } from './Button';

export interface PaginationProps {
  currentPage: number;
  totalPages: number;
  totalItems?: number;
  onPageChange: (page: number) => void;
  className?: string;
  showPageNumbers?: boolean;
}

export const Pagination: React.FC<PaginationProps> = ({
  currentPage,
  totalPages,
  totalItems,
  onPageChange,
  className = '',
  showPageNumbers = true,
}) => {
  const safeTotalPages = Math.max(1, totalPages);
  const canGoPrev = currentPage > 1;
  const canGoNext = currentPage < safeTotalPages;

  // Generate a small range of page numbers around currentPage
  const getPageNumbers = () => {
    const pages: number[] = [];
    const delta = 1;
    const start = Math.max(1, currentPage - delta);
    const end = Math.min(safeTotalPages, currentPage + delta);

    for (let i = start; i <= end; i++) {
      pages.push(i);
    }
    return pages;
  };

  if (safeTotalPages <= 1 && totalItems === undefined) {
    return null;
  }

  return (
    <div className={['pagination', className].filter(Boolean).join(' ')}>
      <div className="pagination-info">
        <span>
          Page <strong>{currentPage}</strong> of <strong>{safeTotalPages}</strong>
        </span>
        {typeof totalItems === 'number' && (
          <span className="text-secondary" style={{ marginLeft: '0.4rem' }}>
            ({totalItems} items)
          </span>
        )}
      </div>

      <div className="pagination-actions">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => onPageChange(1)}
          disabled={!canGoPrev}
          title="First page"
          icon={<ChevronsLeft size={14} />}
        />
        <Button
          variant="secondary"
          size="sm"
          onClick={() => onPageChange(currentPage - 1)}
          disabled={!canGoPrev}
          title="Previous page"
          icon={<ChevronLeft size={14} />}
        />

        {showPageNumbers &&
          safeTotalPages > 1 &&
          getPageNumbers().map(p => (
            <Button
              key={p}
              variant={p === currentPage ? 'primary' : 'secondary'}
              size="sm"
              onClick={() => onPageChange(p)}
            >
              {p}
            </Button>
          ))}

        <Button
          variant="secondary"
          size="sm"
          onClick={() => onPageChange(currentPage + 1)}
          disabled={!canGoNext}
          title="Next page"
          icon={<ChevronRight size={14} />}
        />
        <Button
          variant="secondary"
          size="sm"
          onClick={() => onPageChange(safeTotalPages)}
          disabled={!canGoNext}
          title="Last page"
          icon={<ChevronsRight size={14} />}
        />
      </div>
    </div>
  );
};
