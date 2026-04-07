import { useState, useEffect, useCallback, useMemo } from 'react';
import toast from 'react-hot-toast';
import {
  Plus,
  ChevronDown,
  ChevronUp,
  Play,
  Pause,
  Trash2,
  Clock,
  Zap,
  CalendarClock,
} from 'lucide-react';
import { schedulesApi, projectsApi } from '../../lib/api';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { SettingsSection, SettingsGroup } from '../../components/settings';
import { ConfirmDialog } from '../../components/modals/ConfirmDialog';

interface Schedule {
  id: string;
  name: string;
  cron_expression: string;
  next_run_at: string | null;
  runs_completed: number;
  last_status: string | null;
  paused: boolean;
  prompt_template: string;
  deliver: string;
  project_id: string;
}

interface Project {
  id: string;
  name: string;
  slug: string;
}

function formatDate(dateString: string | null): string {
  if (!dateString) return 'Not scheduled';
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(dateString));
}

function getStatusBadge(status: string | null): { label: string; className: string } {
  if (!status) return { label: 'Never run', className: 'bg-white/5 text-[var(--text-subtle)]' };
  if (status === 'success')
    return { label: 'Success', className: 'bg-green-500/10 text-green-400' };
  if (status === 'failed' || status === 'error')
    return { label: 'Failed', className: 'bg-red-500/10 text-red-400' };
  if (status === 'running') return { label: 'Running', className: 'bg-blue-500/10 text-blue-400' };
  return { label: status, className: 'bg-white/5 text-[var(--text-subtle)]' };
}

export default function SchedulesSettings() {
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedProjectId, setSelectedProjectId] = useState('');

  // Create form
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [formName, setFormName] = useState('');
  const [formExpression, setFormExpression] = useState('');
  const [formPrompt, setFormPrompt] = useState('');
  const [formDeliver, setFormDeliver] = useState('origin');
  const [formProjectId, setFormProjectId] = useState('');
  const [creating, setCreating] = useState(false);

  // Actions
  const [actionLoadingId, setActionLoadingId] = useState<string | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    confirmText: string;
    variant: 'danger' | 'warning' | 'info';
    onConfirm: () => void;
  }>({
    isOpen: false,
    title: '',
    message: '',
    confirmText: 'Confirm',
    variant: 'info',
    onConfirm: () => {},
  });

  const loadData = useCallback(async () => {
    try {
      const [schedulesRes, projectsRes] = await Promise.all([
        schedulesApi.list(selectedProjectId || undefined),
        projectsApi.getAll(),
      ]);
      setSchedules(schedulesRes as Schedule[]);
      setProjects(projectsRes as Project[]);
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to load schedules');
    } finally {
      setLoading(false);
    }
  }, [selectedProjectId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const filteredSchedules = useMemo(() => {
    if (!selectedProjectId) return schedules;
    return schedules.filter((s) => s.project_id === selectedProjectId);
  }, [schedules, selectedProjectId]);

  const resetForm = () => {
    setFormName('');
    setFormExpression('');
    setFormPrompt('');
    setFormDeliver('origin');
    setFormProjectId('');
  };

  const handleCreate = async () => {
    if (!formName.trim() || !formExpression.trim() || !formPrompt.trim() || !formProjectId) return;
    setCreating(true);
    try {
      await schedulesApi.create({
        name: formName.trim(),
        schedule_expression: formExpression.trim(),
        prompt_template: formPrompt.trim(),
        deliver: formDeliver,
        project_id: formProjectId,
      });
      toast.success('Schedule created');
      setShowCreateForm(false);
      resetForm();
      loadData();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to create schedule');
    } finally {
      setCreating(false);
    }
  };

  const handleTrigger = async (scheduleId: string) => {
    setActionLoadingId(scheduleId);
    try {
      const result = await schedulesApi.trigger(scheduleId);
      const res = result as { task_id?: string };
      toast.success(res.task_id ? `Triggered (task: ${res.task_id})` : 'Schedule triggered');
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to trigger schedule');
    } finally {
      setActionLoadingId(null);
    }
  };

  const handlePauseResume = async (schedule: Schedule) => {
    setActionLoadingId(schedule.id);
    try {
      if (schedule.paused) {
        await schedulesApi.resume(schedule.id);
        toast.success('Schedule resumed');
      } else {
        await schedulesApi.pause(schedule.id);
        toast.success('Schedule paused');
      }
      loadData();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to update schedule');
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleDelete = (schedule: Schedule) => {
    setConfirmDialog({
      isOpen: true,
      title: `Delete "${schedule.name}"`,
      message:
        'This schedule will be permanently deleted. Any pending runs will be cancelled. This cannot be undone.',
      confirmText: 'Delete',
      variant: 'danger',
      onConfirm: async () => {
        setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
        setActionLoadingId(schedule.id);
        try {
          await schedulesApi.remove(schedule.id);
          toast.success('Schedule deleted');
          loadData();
        } catch (error: unknown) {
          const err = error as { response?: { data?: { detail?: string } } };
          toast.error(err.response?.data?.detail || 'Failed to delete schedule');
        } finally {
          setActionLoadingId(null);
        }
      },
    });
  };

  const projectName = (id: string) => projects.find((p) => p.id === id)?.name || id;

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading schedules..." size={60} />
      </div>
    );
  }

  return (
    <>
      <SettingsSection
        title="Schedules"
        description="Manage cron schedules for automated agent tasks"
      >
        {/* Project picker */}
        <div>
          <label className="text-xs font-medium text-[var(--text)] block mb-1.5">
            Filter by Project
          </label>
          <select
            value={selectedProjectId}
            onChange={(e) => setSelectedProjectId(e.target.value)}
            className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
          >
            <option value="">All projects</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        {/* Schedules list */}
        <SettingsGroup title="Schedules">
          {filteredSchedules.length > 0 ? (
            <div className="divide-y divide-[var(--border)]">
              {filteredSchedules.map((schedule) => {
                const statusBadge = getStatusBadge(schedule.last_status);
                const isLoading = actionLoadingId === schedule.id;
                return (
                  <div
                    key={schedule.id}
                    className="p-4 hover:bg-[var(--surface-hover)] transition-colors"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex items-start gap-3 flex-1 min-w-0">
                        <div className="w-10 h-10 rounded-lg bg-[var(--primary)]/10 flex items-center justify-center flex-shrink-0 text-[var(--primary)]">
                          <CalendarClock size={20} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <h4 className="font-semibold text-sm text-[var(--text)]">
                              {schedule.name}
                            </h4>
                            {schedule.paused && (
                              <span className="px-2 py-0.5 rounded text-[10px] bg-yellow-500/10 text-yellow-400">
                                Paused
                              </span>
                            )}
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] ${statusBadge.className}`}
                            >
                              {statusBadge.label}
                            </span>
                          </div>
                          <code className="text-xs font-mono text-[var(--text-muted)] bg-[var(--bg)] px-2 py-0.5 rounded mt-1 inline-block">
                            {schedule.cron_expression}
                          </code>
                          <div className="flex items-center gap-3 mt-2 flex-wrap text-[11px] text-[var(--text-subtle)]">
                            <span className="flex items-center gap-1">
                              <Clock size={12} />
                              Next: {formatDate(schedule.next_run_at)}
                            </span>
                            <span>
                              {schedule.runs_completed} run
                              {schedule.runs_completed !== 1 ? 's' : ''} completed
                            </span>
                            <span className="capitalize">{projectName(schedule.project_id)}</span>
                            <span className="px-2 py-0.5 bg-white/5 text-[var(--text-subtle)] rounded text-[10px]">
                              {schedule.deliver}
                            </span>
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-1 flex-shrink-0">
                        <button
                          onClick={() => handleTrigger(schedule.id)}
                          disabled={isLoading}
                          className="p-2 text-[var(--text-subtle)] hover:text-[var(--primary)] hover:bg-[var(--primary)]/10 rounded-lg transition-colors disabled:opacity-50"
                          title="Trigger now"
                        >
                          <Zap size={16} />
                        </button>
                        <button
                          onClick={() => handlePauseResume(schedule)}
                          disabled={isLoading}
                          className="p-2 text-[var(--text-subtle)] hover:text-yellow-400 hover:bg-yellow-500/10 rounded-lg transition-colors disabled:opacity-50"
                          title={schedule.paused ? 'Resume' : 'Pause'}
                        >
                          {schedule.paused ? <Play size={16} /> : <Pause size={16} />}
                        </button>
                        <button
                          onClick={() => handleDelete(schedule)}
                          disabled={isLoading}
                          className="p-2 text-[var(--text-subtle)] hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors disabled:opacity-50"
                          title="Delete schedule"
                        >
                          {isLoading ? (
                            <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                              <circle
                                className="opacity-25"
                                cx="12"
                                cy="12"
                                r="10"
                                stroke="currentColor"
                                strokeWidth="4"
                              />
                              <path
                                className="opacity-75"
                                fill="currentColor"
                                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                              />
                            </svg>
                          ) : (
                            <Trash2 size={16} />
                          )}
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="p-8 text-center">
              <div className="w-12 h-12 rounded-xl bg-[var(--surface-hover)] border border-[var(--border)] flex items-center justify-center mx-auto mb-3">
                <CalendarClock size={24} className="text-[var(--text-subtle)]" />
              </div>
              <p className="text-sm text-[var(--text-muted)] mb-1">No schedules configured</p>
              <p className="text-xs text-[var(--text-subtle)]">
                Create a schedule below to automate agent tasks
              </p>
            </div>
          )}
        </SettingsGroup>

        {/* Create Schedule */}
        <div>
          <button
            onClick={() => setShowCreateForm((prev) => !prev)}
            className="btn flex items-center gap-1.5 w-full justify-between"
          >
            <span className="flex items-center gap-1.5">
              <Plus size={14} />
              Create Schedule
            </span>
            {showCreateForm ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>

          {showCreateForm && (
            <div className="mt-3 p-4 bg-[var(--surface-hover)] border border-[var(--border)] rounded-xl">
              <h4 className="font-semibold text-sm text-[var(--text)] mb-4">New schedule</h4>
              <div className="space-y-4">
                {/* Name */}
                <div>
                  <label className="text-xs font-medium text-[var(--text)] block mb-1.5">
                    Name <span className="text-red-400">*</span>
                  </label>
                  <input
                    type="text"
                    value={formName}
                    onChange={(e) => setFormName(e.target.value)}
                    placeholder="e.g., Daily status report"
                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                    maxLength={100}
                  />
                </div>

                {/* Schedule expression */}
                <div>
                  <label className="text-xs font-medium text-[var(--text)] block mb-1.5">
                    Schedule Expression <span className="text-red-400">*</span>
                  </label>
                  <input
                    type="text"
                    value={formExpression}
                    onChange={(e) => setFormExpression(e.target.value)}
                    placeholder="e.g., daily at 9am or 0 9 * * *"
                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                  />
                  <p className="text-[11px] text-[var(--text-subtle)] mt-1">
                    Accepts natural language like &quot;daily at 9am&quot; or standard cron
                    expressions
                  </p>
                </div>

                {/* Prompt template */}
                <div>
                  <label className="text-xs font-medium text-[var(--text)] block mb-1.5">
                    Prompt Template <span className="text-red-400">*</span>
                  </label>
                  <textarea
                    value={formPrompt}
                    onChange={(e) => setFormPrompt(e.target.value)}
                    placeholder="What should the agent do on each run?"
                    rows={4}
                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)] resize-y"
                  />
                </div>

                {/* Deliver */}
                <div>
                  <label className="text-xs font-medium text-[var(--text)] block mb-1.5">
                    Deliver To
                  </label>
                  <select
                    value={formDeliver}
                    onChange={(e) => setFormDeliver(e.target.value)}
                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                  >
                    <option value="origin">Origin (in-app)</option>
                    <option value="telegram">Telegram</option>
                    <option value="discord">Discord</option>
                    <option value="slack">Slack</option>
                  </select>
                </div>

                {/* Project */}
                <div>
                  <label className="text-xs font-medium text-[var(--text)] block mb-1.5">
                    Project <span className="text-red-400">*</span>
                  </label>
                  <select
                    value={formProjectId}
                    onChange={(e) => setFormProjectId(e.target.value)}
                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                  >
                    <option value="">Select a project</option>
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2 pt-2">
                  <button
                    onClick={handleCreate}
                    disabled={
                      !formName.trim() ||
                      !formExpression.trim() ||
                      !formPrompt.trim() ||
                      !formProjectId ||
                      creating
                    }
                    className="btn btn-filled flex items-center gap-1.5"
                  >
                    {creating ? 'Creating...' : 'Create Schedule'}
                  </button>
                  <button
                    onClick={() => {
                      setShowCreateForm(false);
                      resetForm();
                    }}
                    className="btn"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </SettingsSection>

      <ConfirmDialog
        isOpen={confirmDialog.isOpen}
        onClose={() => setConfirmDialog((prev) => ({ ...prev, isOpen: false }))}
        onConfirm={confirmDialog.onConfirm}
        title={confirmDialog.title}
        message={confirmDialog.message}
        confirmText={confirmDialog.confirmText}
        variant={confirmDialog.variant}
      />
    </>
  );
}
