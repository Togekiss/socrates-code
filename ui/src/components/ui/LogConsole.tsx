import React, { useRef, useEffect } from 'react';
import { RefreshCw, Download, Trash2 } from 'lucide-react';
import { Button } from './Button';

export interface LogConsoleProps {
  logs: string[];
  loading?: boolean;
  onRefresh?: () => void;
  onClear?: () => void;
  onDownload?: () => void;
  downloadFilename?: string;
  title?: string;
  emptyMessage?: string;
  className?: string;
  autoScroll?: boolean;
}

function getLogLineClass(line: string): string {
  const lower = line.toLowerCase();
  if (lower.includes(']error:') || lower.includes('[error]') || lower.includes('traceback (most recent call last)')) {
    return 'log-line--error';
  }
  if (lower.includes(']warning:') || lower.includes('[warning]') || lower.includes('[warn]')) {
    return 'log-line--warning';
  }
  if (lower.includes(']info:') || lower.includes('[info]')) {
    return 'log-line--info';
  }
  if (lower.includes(']success:') || lower.includes('[success]')) {
    return 'log-line--success';
  }
  return 'log-line--base';
}

export const LogConsole: React.FC<LogConsoleProps> = ({
  logs,
  loading = false,
  onRefresh,
  onClear,
  onDownload,
  downloadFilename = 'console-logs.txt',
  title = 'Live Console',
  emptyMessage = 'No log entries recorded.',
  className = '',
  autoScroll = true,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  const handleDownload = () => {
    if (logs.length === 0) return;
    if (onDownload) {
      onDownload();
      return;
    }
    const blob = new Blob([logs.join('\n')], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = downloadFilename;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className={['log-console-wrapper', className].filter(Boolean).join(' ')}>
      <div className="log-console-header">
        <h4 className="log-console-title">{title}</h4>
        <div className="log-console-actions">
          {onRefresh && (
            <Button
              variant="secondary"
              size="xs"
              onClick={onRefresh}
              loading={loading}
              icon={<RefreshCw size={12} />}
            >
              Refresh
            </Button>
          )}
          {onClear && (
            <Button
              variant="ghost"
              size="xs"
              onClick={onClear}
              disabled={logs.length === 0}
              icon={<Trash2 size={12} />}
            >
              Clear
            </Button>
          )}
          <Button
            variant="secondary"
            size="xs"
            onClick={handleDownload}
            disabled={logs.length === 0}
            icon={<Download size={12} />}
          >
            Download
          </Button>
        </div>
      </div>

      <div ref={containerRef} className="log-console">
        {logs.length === 0 ? (
          <div className="log-console-empty">{emptyMessage}</div>
        ) : (
          logs.map((line, idx) => (
            <div
              key={`${idx}-${line.slice(0, 20)}`}
              className={['log-line', getLogLineClass(line)].join(' ')}
            >
              {line}
            </div>
          ))
        )}
      </div>
    </div>
  );
};
