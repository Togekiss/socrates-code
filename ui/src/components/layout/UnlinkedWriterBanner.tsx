import React from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertCircle, UserCheck } from 'lucide-react';

export interface UnlinkedWriterBannerProps {
  onNavigateToWriters?: () => void;
  className?: string;
}

export const UnlinkedWriterBanner: React.FC<UnlinkedWriterBannerProps> = ({
  onNavigateToWriters,
  className = '',
}) => {
  const navigate = useNavigate();

  const handleAction = () => {
    if (onNavigateToWriters) {
      onNavigateToWriters();
    } else {
      navigate('/writers');
    }
  };

  return (
    <div className={`banner-warning ${className}`.trim()} role="alert">
      <div className="banner-content">
        <AlertCircle size={22} className="flex-shrink-0" />
        <div>
          <div className="banner-title">Your Discord account is not linked to a writer profile</div>
          <div className="banner-subtitle">
            Link your Discord user ID in the Writers view so &quot;★ By Me&quot; can identify your characters.
          </div>
        </div>
      </div>
      <button
        type="button"
        className="btn btn-warning btn-sm"
        onClick={handleAction}
      >
        <UserCheck size={14} /> Go to Writers
      </button>
    </div>
  );
};

export default UnlinkedWriterBanner;
