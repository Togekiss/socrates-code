import React, { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';

export type ModalSize = 'sm' | 'md' | 'lg' | 'xl';

export interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: React.ReactNode;
  size?: ModalSize;
  footer?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  closeOnBackdropClick?: boolean;
}

export const Modal: React.FC<ModalProps> = ({
  isOpen,
  onClose,
  title,
  size = 'md',
  footer,
  children,
  className = '',
  closeOnBackdropClick = true,
}) => {
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = prevOverflow;
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const dialogClasses = [
    'modal-dialog',
    `modal-${size}`,
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return createPortal(
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      onClick={e => {
        if (closeOnBackdropClick && e.target === e.currentTarget) {
          onClose();
        }
      }}
    >
      <div className={dialogClasses}>
        <div className="modal-header">
          {typeof title === 'string' ? (
            <h3 className="modal-title">{title}</h3>
          ) : (
            <div className="modal-title">{title}</div>
          )}
          <button
            type="button"
            className="modal-close"
            onClick={onClose}
            aria-label="Close dialog"
          >
            <X size={18} />
          </button>
        </div>

        <div className="modal-body">{children}</div>

        {footer && <div className="modal-footer">{footer}</div>}
      </div>
    </div>,
    document.body
  );
};
