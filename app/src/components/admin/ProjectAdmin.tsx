import { useState, useEffect, useCallback } from 'react';
import {
  Search,
  FolderOpen,
  Eye,
  Pause,
  Trash2,
  UserPlus,
  ChevronLeft,
  ChevronRight,
  X,
  AlertTriangle,
  Globe,
  GitBranch,
  Box,
} from 'lucide-react';
import { getAuthHeaders } from '../../lib/api';
import toast from 'react-hot-toast';
import { LoadingSpinner } from '../PulsingGridSpinner';

interface ProjectListItem {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  owner_id: string;
  owner_username: string | null;
  owner_email: string | null;
  environment_status: string;
  is_deployed: boolean;
  deploy_type: string;
  has_git_repo: boolean;
  deployment_count: number;
  last_activity: string | null;
  hibernated_at: string | null;
  created_at: string | null;
}

interface ProjectDetail extends ProjectListItem {
  owner: {
    id: string | null;
    username: string | null;
    email: string | null;
  };
  deployed_at: string | null;
  git_remote_url: string | null;
  network_name: string | null;
  volume_name: string | null;
  file_count: number;
  containers: Array<{
    id: string;
    name: string;
    container_type: string;
    status: string;
    port: number;
  }>;
  recent_deployments: Array<{
    id: string;
    provider: string;
    status: string;
    deployment_url: string | null;
    created_at: string | null;
  }>;
  updated_at: string | null;
}

interface ProjectsResponse {
  projects: ProjectListItem[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

const STATUS_COLORS: Record<string, string> = {
  active: 'bg-green-500/20 text-green-400',
  hibernated: 'bg-yellow-500/20 text-yellow-400',
  starting: 'bg-blue-500/20 text-blue-400',
  stopping: 'bg-orange-500/20 text-orange-400',
};

export default function ProjectAdmin() {
  const [projects, setProjects] = useState<ProjectListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(25);
  const [pages, setPages] = useState(0);

  // Filters
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [deploymentFilter, setDeploymentFilter] = useState('');

  // Modal states
  const [selectedProject, setSelectedProject] = useState<ProjectDetail | null>(null);
  const [showDetailModal, setShowDetailModal] = useState(false);
  const [showHibernateModal, setShowHibernateModal] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [showTransferModal, setShowTransferModal] = useState(false);

  // Action states
  const [actionLoading, setActionLoading] = useState(false);
  const [hibernateReason, setHibernateReason] = useState('');
  const [deleteReason, setDeleteReason] = useState('');
  const [newOwnerId, setNewOwnerId] = useState('');
  const [transferReason, setTransferReason] = useState('');

  const loadProjects = useCallback(async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (search) params.append('search', search);
      if (statusFilter) params.append('status', statusFilter);
      if (deploymentFilter) params.append('deployment_status', deploymentFilter);
      params.append('page', page.toString());
      params.append('page_size', pageSize.toString());

      const response = await fetch(`/api/admin/projects?${params.toString()}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to load projects');

      const data: ProjectsResponse = await response.json();
      setProjects(data.projects);
      setTotal(data.total);
      setPages(data.pages);
    } catch (error) {
      console.error('Failed to load projects:', error);
      toast.error('Failed to load projects');
    } finally {
      setLoading(false);
    }
  }, [search, statusFilter, deploymentFilter, page, pageSize]);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  const loadProjectDetail = async (projectId: string) => {
    try {
      const response = await fetch(`/api/admin/projects/${projectId}`, {
        headers: getAuthHeaders(),
        credentials: 'include',
      });

      if (!response.ok) throw new Error('Failed to load project details');

      const data: ProjectDetail = await response.json();
      setSelectedProject(data);
      setShowDetailModal(true);
    } catch (error) {
      console.error('Failed to load project details:', error);
      toast.error('Failed to load project details');
    }
  };

  const handleHibernate = async () => {
    if (!selectedProject || !hibernateReason.trim()) return;

    try {
      setActionLoading(true);
      const response = await fetch(`/api/admin/projects/${selectedProject.id}/hibernate`, {
        method: 'POST',
        headers: getAuthHeaders(),
        credentials: 'include',
        body: JSON.stringify({ reason: hibernateReason }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to hibernate project');
      }

      toast.success('Project hibernated successfully');
      setShowHibernateModal(false);
      setHibernateReason('');
      loadProjects();
    } catch (error) {
      console.error('Failed to hibernate project:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to hibernate project');
    } finally {
      setActionLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedProject || !deleteReason.trim()) return;

    try {
      setActionLoading(true);
      const response = await fetch(`/api/admin/projects/${selectedProject.id}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
        credentials: 'include',
        body: JSON.stringify({ reason: deleteReason }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to delete project');
      }

      toast.success('Project deleted successfully');
      setShowDeleteModal(false);
      setDeleteReason('');
      loadProjects();
    } catch (error) {
      console.error('Failed to delete project:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to delete project');
    } finally {
      setActionLoading(false);
    }
  };

  const handleTransfer = async () => {
    if (!selectedProject || !newOwnerId.trim() || !transferReason.trim()) return;

    try {
      setActionLoading(true);
      const response = await fetch(`/api/admin/projects/${selectedProject.id}/transfer`, {
        method: 'POST',
        headers: getAuthHeaders(),
        credentials: 'include',
        body: JSON.stringify({ new_owner_id: newOwnerId, reason: transferReason }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to transfer project');
      }

      toast.success('Project transferred successfully');
      setShowTransferModal(false);
      setNewOwnerId('');
      setTransferReason('');
      loadProjects();
    } catch (error) {
      console.error('Failed to transfer project:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to transfer project');
    } finally {
      setActionLoading(false);
    }
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleDateString();
  };

  const formatDateTime = (dateStr: string | null) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleString();
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FolderOpen className="h-5 w-5 text-zinc-400" />
          <h2 className="text-lg font-semibold text-white">Project Administration</h2>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-zinc-500" />
          <input
            type="text"
            placeholder="Search by name or slug..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            className="w-full pl-9 pr-4 py-2 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white placeholder:text-zinc-500 focus:outline-none focus:border-zinc-700"
          />
        </div>

        <select
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value);
            setPage(1);
          }}
          className="px-3 py-2 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white focus:outline-none focus:border-zinc-700"
        >
          <option value="">All Status</option>
          <option value="active">Active</option>
          <option value="hibernated">Hibernated</option>
        </select>

        <select
          value={deploymentFilter}
          onChange={(e) => {
            setDeploymentFilter(e.target.value);
            setPage(1);
          }}
          className="px-3 py-2 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white focus:outline-none focus:border-zinc-700"
        >
          <option value="">All Deployment Status</option>
          <option value="deployed">Deployed</option>
          <option value="development">Development</option>
        </select>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <LoadingSpinner size={32} />
        </div>
      ) : projects.length === 0 ? (
        <div className="text-center py-12 text-zinc-500">No projects found</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-zinc-500 border-b border-zinc-800">
                <th className="pb-3 font-medium">Project</th>
                <th className="pb-3 font-medium">Owner</th>
                <th className="pb-3 font-medium">Status</th>
                <th className="pb-3 font-medium">Deploy</th>
                <th className="pb-3 font-medium">Git</th>
                <th className="pb-3 font-medium">Deployments</th>
                <th className="pb-3 font-medium">Created</th>
                <th className="pb-3 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {projects.map((project) => (
                <tr key={project.id} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                  <td className="py-3">
                    <div>
                      <p className="text-white font-medium">{project.name}</p>
                      <p className="text-xs text-zinc-500 font-mono">{project.slug}</p>
                    </div>
                  </td>
                  <td className="py-3">
                    <div>
                      <p className="text-white">@{project.owner_username || '-'}</p>
                      <p className="text-xs text-zinc-500">{project.owner_email || ''}</p>
                    </div>
                  </td>
                  <td className="py-3">
                    <span
                      className={`px-2 py-1 rounded text-xs font-medium ${STATUS_COLORS[project.environment_status] || 'bg-zinc-700 text-zinc-300'}`}
                    >
                      {project.environment_status}
                    </span>
                  </td>
                  <td className="py-3">
                    {project.is_deployed ? (
                      <span className="flex items-center gap-1 text-green-400">
                        <Globe className="h-4 w-4" />
                        Deployed
                      </span>
                    ) : (
                      <span className="text-zinc-500">Development</span>
                    )}
                  </td>
                  <td className="py-3">
                    {project.has_git_repo ? (
                      <GitBranch className="h-4 w-4 text-green-400" />
                    ) : (
                      <span className="text-zinc-600">-</span>
                    )}
                  </td>
                  <td className="py-3 text-zinc-400">{project.deployment_count}</td>
                  <td className="py-3 text-zinc-400">{formatDate(project.created_at)}</td>
                  <td className="py-3">
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => loadProjectDetail(project.id)}
                        className="p-1 hover:bg-zinc-700 rounded"
                        title="View Details"
                      >
                        <Eye className="h-4 w-4 text-zinc-400" />
                      </button>
                      {project.environment_status === 'active' && (
                        <button
                          onClick={() => {
                            setSelectedProject(project as unknown as ProjectDetail);
                            setShowHibernateModal(true);
                          }}
                          className="p-1 hover:bg-zinc-700 rounded"
                          title="Hibernate"
                        >
                          <Pause className="h-4 w-4 text-yellow-400" />
                        </button>
                      )}
                      <button
                        onClick={() => {
                          setSelectedProject(project as unknown as ProjectDetail);
                          setShowTransferModal(true);
                        }}
                        className="p-1 hover:bg-zinc-700 rounded"
                        title="Transfer"
                      >
                        <UserPlus className="h-4 w-4 text-purple-400" />
                      </button>
                      <button
                        onClick={() => {
                          setSelectedProject(project as unknown as ProjectDetail);
                          setShowDeleteModal(true);
                        }}
                        className="p-1 hover:bg-zinc-700 rounded"
                        title="Delete"
                      >
                        <Trash2 className="h-4 w-4 text-red-400" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {pages > 1 && (
        <div className="flex items-center justify-between pt-4">
          <span className="text-sm text-zinc-500">
            Showing {(page - 1) * pageSize + 1} - {Math.min(page * pageSize, total)} of {total}{' '}
            projects
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="p-2 hover:bg-zinc-800 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <ChevronLeft className="h-4 w-4 text-zinc-400" />
            </button>
            <span className="text-sm text-zinc-400">
              Page {page} of {pages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(pages, p + 1))}
              disabled={page === pages}
              className="p-2 hover:bg-zinc-800 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <ChevronRight className="h-4 w-4 text-zinc-400" />
            </button>
          </div>
        </div>
      )}

      {/* Detail Modal */}
      {showDetailModal && selectedProject && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-zinc-900 rounded-xl border border-zinc-800 w-full max-w-3xl max-h-[80vh] overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b border-zinc-800">
              <div>
                <h3 className="font-semibold text-white">{selectedProject.name}</h3>
                <p className="text-sm text-zinc-500 font-mono">{selectedProject.slug}</p>
              </div>
              <button
                onClick={() => setShowDetailModal(false)}
                className="p-1 hover:bg-zinc-800 rounded"
              >
                <X className="h-5 w-5 text-zinc-400" />
              </button>
            </div>
            <div className="p-4 space-y-4 overflow-y-auto max-h-[60vh]">
              {/* Status Cards */}
              <div className="grid grid-cols-4 gap-4">
                <div className="bg-zinc-800/50 rounded-lg p-3">
                  <p className="text-xs text-zinc-500">Status</p>
                  <p
                    className={`mt-1 px-2 py-1 rounded text-sm font-medium inline-block ${STATUS_COLORS[selectedProject.environment_status] || 'bg-zinc-700'}`}
                  >
                    {selectedProject.environment_status}
                  </p>
                </div>
                <div className="bg-zinc-800/50 rounded-lg p-3">
                  <p className="text-xs text-zinc-500">Deploy Type</p>
                  <p className="text-white font-medium mt-1">{selectedProject.deploy_type}</p>
                </div>
                <div className="bg-zinc-800/50 rounded-lg p-3">
                  <p className="text-xs text-zinc-500">Files</p>
                  <p className="text-white font-medium mt-1">{selectedProject.file_count}</p>
                </div>
                <div className="bg-zinc-800/50 rounded-lg p-3">
                  <p className="text-xs text-zinc-500">Containers</p>
                  <p className="text-white font-medium mt-1">
                    {selectedProject.containers?.length || 0}
                  </p>
                </div>
              </div>

              {/* Owner Info */}
              <div className="bg-zinc-800/50 rounded-lg p-4">
                <h4 className="text-sm font-medium text-zinc-400 mb-2">Owner</h4>
                <p className="text-white">@{selectedProject.owner?.username || '-'}</p>
                <p className="text-sm text-zinc-500">{selectedProject.owner?.email}</p>
              </div>

              {/* Containers */}
              {selectedProject.containers && selectedProject.containers.length > 0 && (
                <div className="bg-zinc-800/50 rounded-lg p-4">
                  <h4 className="text-sm font-medium text-zinc-400 mb-2 flex items-center gap-2">
                    <Box className="h-4 w-4" /> Containers
                  </h4>
                  <div className="space-y-2">
                    {selectedProject.containers.map((c) => (
                      <div key={c.id} className="flex items-center justify-between text-sm">
                        <span className="text-white">{c.name}</span>
                        <span className="text-zinc-500">
                          {c.container_type} - Port {c.port}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Recent Deployments */}
              {selectedProject.recent_deployments &&
                selectedProject.recent_deployments.length > 0 && (
                  <div className="bg-zinc-800/50 rounded-lg p-4">
                    <h4 className="text-sm font-medium text-zinc-400 mb-2 flex items-center gap-2">
                      <Globe className="h-4 w-4" /> Recent Deployments
                    </h4>
                    <div className="space-y-2">
                      {selectedProject.recent_deployments.map((d) => (
                        <div key={d.id} className="flex items-center justify-between text-sm">
                          <span className="text-white">{d.provider}</span>
                          <span
                            className={
                              d.status === 'success'
                                ? 'text-green-400'
                                : d.status === 'failed'
                                  ? 'text-red-400'
                                  : 'text-yellow-400'
                            }
                          >
                            {d.status}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

              {/* Timestamps */}
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-zinc-500">Created:</span>
                  <span className="text-white ml-2">
                    {formatDateTime(selectedProject.created_at)}
                  </span>
                </div>
                <div>
                  <span className="text-zinc-500">Last Activity:</span>
                  <span className="text-white ml-2">
                    {formatDateTime(selectedProject.last_activity)}
                  </span>
                </div>
              </div>
            </div>
            <div className="p-4 border-t border-zinc-800 flex gap-2">
              {selectedProject.environment_status === 'active' && (
                <button
                  onClick={() => {
                    setShowDetailModal(false);
                    setShowHibernateModal(true);
                  }}
                  className="flex-1 px-4 py-2 bg-yellow-600 hover:bg-yellow-700 rounded-lg text-white flex items-center justify-center gap-2"
                >
                  <Pause className="h-4 w-4" /> Hibernate
                </button>
              )}
              <button
                onClick={() => {
                  setShowDetailModal(false);
                  setShowTransferModal(true);
                }}
                className="flex-1 px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-white flex items-center justify-center gap-2"
              >
                <UserPlus className="h-4 w-4" /> Transfer
              </button>
              <button
                onClick={() => {
                  setShowDetailModal(false);
                  setShowDeleteModal(true);
                }}
                className="flex-1 px-4 py-2 bg-red-600 hover:bg-red-700 rounded-lg text-white flex items-center justify-center gap-2"
              >
                <Trash2 className="h-4 w-4" /> Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Hibernate Modal */}
      {showHibernateModal && selectedProject && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-zinc-900 rounded-xl border border-zinc-800 w-full max-w-md">
            <div className="p-4 border-b border-zinc-800">
              <h3 className="font-semibold text-white flex items-center gap-2">
                <Pause className="h-5 w-5 text-yellow-400" />
                Hibernate Project
              </h3>
            </div>
            <div className="p-4 space-y-4">
              <p className="text-zinc-400">
                Are you sure you want to hibernate{' '}
                <span className="text-white font-medium">{selectedProject.name}</span>? This will
                stop all containers and save the project state.
              </p>
              <div>
                <label className="text-sm text-zinc-500">Reason (required)</label>
                <textarea
                  value={hibernateReason}
                  onChange={(e) => setHibernateReason(e.target.value)}
                  placeholder="Why are you hibernating this project?"
                  className="w-full mt-1 p-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder:text-zinc-500 resize-none"
                  rows={3}
                />
              </div>
            </div>
            <div className="p-4 border-t border-zinc-800 flex gap-2">
              <button
                onClick={() => {
                  setShowHibernateModal(false);
                  setHibernateReason('');
                }}
                className="flex-1 px-4 py-2 bg-zinc-800 hover:bg-zinc-700 rounded-lg text-white"
              >
                Cancel
              </button>
              <button
                onClick={handleHibernate}
                disabled={actionLoading || !hibernateReason.trim()}
                className="flex-1 px-4 py-2 bg-yellow-600 hover:bg-yellow-700 rounded-lg text-white disabled:opacity-50"
              >
                {actionLoading ? 'Hibernating...' : 'Hibernate'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Modal */}
      {showDeleteModal && selectedProject && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-zinc-900 rounded-xl border border-zinc-800 w-full max-w-md">
            <div className="p-4 border-b border-zinc-800">
              <h3 className="font-semibold text-white flex items-center gap-2">
                <AlertTriangle className="h-5 w-5 text-red-400" />
                Delete Project
              </h3>
            </div>
            <div className="p-4 space-y-4">
              <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3">
                <p className="text-red-400 text-sm">
                  This action is permanent. All project files, containers, and deployments will be
                  deleted.
                </p>
              </div>
              <p className="text-zinc-400">
                Delete <span className="text-white font-medium">{selectedProject.name}</span>?
              </p>
              <div>
                <label className="text-sm text-zinc-500">Reason (required)</label>
                <textarea
                  value={deleteReason}
                  onChange={(e) => setDeleteReason(e.target.value)}
                  placeholder="Why are you deleting this project?"
                  className="w-full mt-1 p-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder:text-zinc-500 resize-none"
                  rows={3}
                />
              </div>
            </div>
            <div className="p-4 border-t border-zinc-800 flex gap-2">
              <button
                onClick={() => {
                  setShowDeleteModal(false);
                  setDeleteReason('');
                }}
                className="flex-1 px-4 py-2 bg-zinc-800 hover:bg-zinc-700 rounded-lg text-white"
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                disabled={actionLoading || !deleteReason.trim()}
                className="flex-1 px-4 py-2 bg-red-600 hover:bg-red-700 rounded-lg text-white disabled:opacity-50"
              >
                {actionLoading ? 'Deleting...' : 'Delete Project'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Transfer Modal */}
      {showTransferModal && selectedProject && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-zinc-900 rounded-xl border border-zinc-800 w-full max-w-md">
            <div className="p-4 border-b border-zinc-800">
              <h3 className="font-semibold text-white flex items-center gap-2">
                <UserPlus className="h-5 w-5 text-purple-400" />
                Transfer Ownership
              </h3>
            </div>
            <div className="p-4 space-y-4">
              <p className="text-zinc-400">
                Transfer <span className="text-white font-medium">{selectedProject.name}</span> to
                another user.
              </p>
              <div>
                <label className="text-sm text-zinc-500">New Owner ID (required)</label>
                <input
                  type="text"
                  value={newOwnerId}
                  onChange={(e) => setNewOwnerId(e.target.value)}
                  placeholder="Enter user UUID"
                  className="w-full mt-1 p-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder:text-zinc-500 font-mono text-sm"
                />
              </div>
              <div>
                <label className="text-sm text-zinc-500">Reason (required)</label>
                <textarea
                  value={transferReason}
                  onChange={(e) => setTransferReason(e.target.value)}
                  placeholder="Why are you transferring this project?"
                  className="w-full mt-1 p-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder:text-zinc-500 resize-none"
                  rows={3}
                />
              </div>
            </div>
            <div className="p-4 border-t border-zinc-800 flex gap-2">
              <button
                onClick={() => {
                  setShowTransferModal(false);
                  setNewOwnerId('');
                  setTransferReason('');
                }}
                className="flex-1 px-4 py-2 bg-zinc-800 hover:bg-zinc-700 rounded-lg text-white"
              >
                Cancel
              </button>
              <button
                onClick={handleTransfer}
                disabled={actionLoading || !newOwnerId.trim() || !transferReason.trim()}
                className="flex-1 px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-white disabled:opacity-50"
              >
                {actionLoading ? 'Transferring...' : 'Transfer'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
