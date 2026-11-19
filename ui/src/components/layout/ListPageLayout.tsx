import React, { useState } from 'react';
import { Info } from 'lucide-react';
import { Modal, ResponsiveText } from '../ui';
import type { ResponsiveTextKey } from '../../utils';
import { PAGE_GUIDES, type PageGuideKey } from './pageGuides';

export interface ListPageLayoutProps {
  title: string;
  descriptionKey?: ResponsiveTextKey;
  description?: React.ReactNode;
  guideKey?: PageGuideKey;
  infoTitle?: string;
  infoContent?: React.ReactNode;
  headerAction?: React.ReactNode;
  filterBar?: React.ReactNode;
  banners?: React.ReactNode;
  countText?: React.ReactNode;
  scrollRef?: React.RefObject<HTMLDivElement | null>;
  children: React.ReactNode;
  modals?: React.ReactNode;
}

export const ListPageLayout: React.FC<ListPageLayoutProps> = ({
  title,
  descriptionKey,
  description,
  guideKey,
  infoTitle,
  infoContent,
  headerAction,
  filterBar,
  banners,
  countText,
  scrollRef,
  children,
  modals,
}) => {
  const [isInfoOpen, setIsInfoOpen] = useState(false);
  const guide = guideKey ? PAGE_GUIDES[guideKey] : undefined;
  const resolvedInfoTitle = infoTitle ?? guide?.title ?? `About ${title}`;
  const resolvedInfoContent = infoContent ?? guide?.content;

  return (
    <div className="list-page">
      <div className="list-page-fixed">
        <div className="list-page-header">
          <div className="list-page-heading">
            <div className="list-page-title-row">
              <h2 className="list-page-title">{title}</h2>
              {resolvedInfoContent && (
                <button
                  type="button"
                  className="list-page-info-btn"
                  onClick={() => setIsInfoOpen(true)}
                  title={`About ${title}`}
                  aria-label={`About ${title}`}
                >
                  <Info size={16} />
                </button>
              )}
            </div>
            {(descriptionKey || description) && (
              <p className="list-page-desc hide-in-mobile">
                {descriptionKey ? <ResponsiveText textKey={descriptionKey} /> : description}
              </p>
            )}
          </div>

          {headerAction && <div className="list-page-action">{headerAction}</div>}
        </div>

        {filterBar}
        {banners}
        {countText && <div className="list-page-count">{countText}</div>}
      </div>

      <div ref={scrollRef} className="list-page-scroll">
        {children}
      </div>

      {resolvedInfoContent && (
        <Modal
          isOpen={isInfoOpen}
          onClose={() => setIsInfoOpen(false)}
          title={resolvedInfoTitle}
          size="md"
        >
          <div className="info-modal-guide">{resolvedInfoContent}</div>
        </Modal>
      )}

      {modals}
    </div>
  );
};
