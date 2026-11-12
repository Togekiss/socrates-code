import { useEffect, useState } from 'react';
import { api } from '../api';
import {
  RotateCcw,
  Database,
  Play,
  CheckCircle,
  XCircle,
  FlaskConical,
} from 'lucide-react';
import { PanelSurface, Button, LogConsole } from './ui';
import type { AdminTestActionResponse, GlobalConfig } from '../types';

interface AdminTabProps {
  onRefreshSummary?: () => void;
}

export const AdminTab = ({ onRefreshSummary }: AdminTabProps) => {
  const [globalConfig, setGlobalConfig] = useState<GlobalConfig | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [loadingLogs, setLoadingLogs] = useState(false);

  const [activeTestAction, setActiveTestAction] = useState<'reset' | 'migrate' | 'suite' | 'upgrade-all' | null>(null);
  const [testResult, setTestResult] = useState<AdminTestActionResponse | null>(null);

  const fetchLogs = () => {
    setLoadingLogs(true);
    api.getGlobalLogs(100)
      .then(res => setLogs(res.logs || []))
      .catch(console.error)
      .finally(() => setLoadingLogs(false));
  };

  const fetchConfig = () => {
    api.getGlobalConfig().then(res => setGlobalConfig(res)).catch(console.error);
  };

  useEffect(() => {
    fetchLogs();
    fetchConfig();
  }, []);

  const clearLogs = () => {
    api.clearGlobalLogs().then(() => setLogs([])).catch(console.error);
  };

  const updateVerbosity = (key: string, value: boolean) => {
    if (!globalConfig || !globalConfig.admin) return;
    const newConfig: GlobalConfig = {
      ...globalConfig,
      admin: {
        ...globalConfig.admin,
        verbosity: {
          ...globalConfig.admin.verbosity,
          [key]: value,
        },
      },
    };
    setGlobalConfig(newConfig);
    api.updateGlobalConfig(newConfig).catch(console.error);
  };

  const handleTestAction = async (action: 'reset' | 'migrate' | 'suite' | 'upgrade-all') => {
    if (activeTestAction) return;
    setActiveTestAction(action);
    setTestResult(null);

    try {
      let res: AdminTestActionResponse;
      if (action === 'reset') {
        res = await api.resetTestingBackup();
      } else if (action === 'migrate') {
        res = await api.migrateTestingBackup();
      } else if (action === 'upgrade-all') {
        res = await api.upgradeAllDatabases();
      } else {
        res = await api.runPythonTests();
      }
      setTestResult(res);
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Action failed';
      setTestResult({
        status: 'failed',
        message: errorMsg,
      });
    } finally {
      setActiveTestAction(null);
      fetchLogs();
      onRefreshSummary?.();
    }
  };

  const isTestBusy = activeTestAction !== null;

  return (
    <div className="flex-col gap-lg">
      {/* Testing & Verification Section */}
      <PanelSurface className="flex-col gap-md">
        <div className="flex-row items-center gap-sm">
          <FlaskConical size={20} style={{ color: 'var(--accent-secondary)' }} />
          <h2 style={{ margin: 0, fontSize: '1.25rem', color: 'var(--text-primary)' }}>
            Testing &amp; Verification
          </h2>
        </div>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', margin: 0 }}>
          Manage the reversible testing dataset (<code>Elysium-sql-tests</code>) and run the automated Python test suite.
        </p>

        <div className="flex-row items-center gap-sm flex-wrap">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => handleTestAction('reset')}
            disabled={isTestBusy}
            loading={activeTestAction === 'reset'}
            icon={<RotateCcw size={15} />}
          >
            Reset Testing Backup
          </Button>

          <Button
            variant="secondary"
            size="sm"
            onClick={() => handleTestAction('migrate')}
            disabled={isTestBusy}
            loading={activeTestAction === 'migrate'}
            icon={<Database size={15} />}
          >
            Migrate Testing Backup
          </Button>

          <Button
            variant="secondary"
            size="sm"
            onClick={() => handleTestAction('upgrade-all')}
            disabled={isTestBusy}
            loading={activeTestAction === 'upgrade-all'}
            icon={<Database size={15} />}
          >
            Upgrade all databases
          </Button>

          <Button
            variant="primary"
            size="sm"
            onClick={() => handleTestAction('suite')}
            disabled={isTestBusy}
            loading={activeTestAction === 'suite'}
            icon={<Play size={15} />}
          >
            Run Python Test Suite
          </Button>
        </div>

        {testResult && (
          <div className="flex-col gap-sm" style={{ marginTop: '0.5rem' }}>
            <div
              className={`banner-${testResult.status === 'success' ? 'success' : 'danger'}`}
              style={{ marginBottom: 0 }}
            >
              <div className="flex-row items-center gap-sm">
                {testResult.status === 'success' ? <CheckCircle size={18} /> : <XCircle size={18} />}
                <strong>{testResult.message}</strong>
              </div>
            </div>

            {testResult.output && (
              <div
                className="log-console"
                style={{
                  height: 'auto',
                  maxHeight: '300px',
                  whiteSpace: 'pre-wrap',
                }}
              >
                {testResult.output}
              </div>
            )}
          </div>
        )}
      </PanelSurface>

      {/* Activity and Logs Section */}
      <PanelSurface className="flex-col gap-md">
        <h2 style={{ margin: 0, fontSize: '1.25rem', color: 'var(--text-primary)' }}>
          Activity and Logging Configuration
        </h2>

        {globalConfig && globalConfig.admin && (
          <div className="flex-row gap-xl flex-wrap">
            <div className="flex-col gap-xs">
              <span className="sidebar-group-title" style={{ padding: 0 }}>Verbosity levels</span>
              <div className="flex-col gap-xs">
                {['info', 'debug', 'console', 'log'].map(key => (
                  <label key={key} className="flex-row items-center gap-xs" style={{ cursor: 'pointer', fontSize: '0.85rem' }}>
                    <input
                      type="checkbox"
                      checked={Boolean(globalConfig.admin?.verbosity?.[key])}
                      onChange={e => updateVerbosity(key, e.target.checked)}
                    />
                    <span>Show {key} messages</span>
                  </label>
                ))}
              </div>
            </div>

            <div className="flex-col gap-xs">
              <span className="sidebar-group-title" style={{ padding: 0 }}>Other settings</span>
              <div className="flex-col gap-xs">
                <label className="flex-row items-center gap-xs" style={{ cursor: 'pointer', fontSize: '0.85rem' }}>
                  <input
                    type="checkbox"
                    checked={Boolean(globalConfig.admin?.verbosity?.debugFiles)}
                    onChange={e => updateVerbosity('debugFiles', e.target.checked)}
                  />
                  <span>Keep debug files</span>
                </label>
                <label className="flex-row items-center gap-xs" style={{ cursor: 'pointer', fontSize: '0.85rem' }}>
                  <input
                    type="checkbox"
                    checked={Boolean(globalConfig.admin?.verbosity?.dryRun)}
                    onChange={e => updateVerbosity('dryRun', e.target.checked)}
                  />
                  <span>Dry run mode</span>
                </label>
              </div>
            </div>
          </div>
        )}

        <LogConsole
          logs={logs}
          loading={loadingLogs}
          onRefresh={fetchLogs}
          onClear={clearLogs}
          downloadFilename="global-log.txt"
          title="Global API & Init Logs"
        />
      </PanelSurface>
    </div>
  );
};
