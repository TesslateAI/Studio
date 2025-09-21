import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { projectsApi } from '../lib/api';
import { 
  Plus, Folder, Trash2, LogOut, Search, Filter, Grid3X3, List, 
  Calendar, Clock, Star, Settings, User, MoreHorizontal, Eye,
  Code, Zap, Activity, TrendingUp, Download, Share2, Copy,
  FolderOpen, RefreshCw, Archive
} from 'lucide-react';
import toast from 'react-hot-toast';

interface Project {
  id: number;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newProject, setNewProject] = useState({ name: '', description: '' });
  const [searchTerm, setSearchTerm] = useState('');
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [sortBy, setSortBy] = useState<'name' | 'date' | 'updated'>('updated');
  const [filterBy, setFilterBy] = useState<'all' | 'recent' | 'starred'>('all');
  const [selectedProjects, setSelectedProjects] = useState<number[]>([]);
  const [isCreating, setIsCreating] = useState(false);

  useEffect(() => {
    loadProjects();
  }, []);

  const loadProjects = async () => {
    try {
      const data = await projectsApi.getAll();
      setProjects(data);
    } catch (error) {
      toast.error('Failed to load projects');
    } finally {
      setLoading(false);
    }
  };

  const createProject = async () => {
    if (!newProject.name.trim()) {
      toast.error('Project name is required');
      return;
    }

    setIsCreating(true);
    const creatingToast = toast.loading('Creating your project...', { duration: 0 });

    try {
      // Simulate creation steps with visual feedback
      toast.loading('Setting up project structure...', { id: creatingToast });
      await new Promise(resolve => setTimeout(resolve, 800));
      
      toast.loading('Initializing development environment...', { id: creatingToast });
      await new Promise(resolve => setTimeout(resolve, 600));
      
      toast.loading('Configuring build tools...', { id: creatingToast });
      const project = await projectsApi.create(newProject.name, newProject.description);
      
      toast.success('Project created successfully!', { id: creatingToast });
      setShowCreateModal(false);
      setNewProject({ name: '', description: '' });
      
      // Brief delay to show success before navigation
      setTimeout(() => {
        navigate(`/project/${project.id}`);
      }, 1000);
    } catch (error) {
      toast.error('Failed to create project', { id: creatingToast });
    } finally {
      setIsCreating(false);
    }
  };

  const deleteProject = async (id: number) => {
    const project = projects.find(p => p.id === id);
    if (!confirm(`Are you sure you want to delete "${project?.name}"? This action cannot be undone.`)) return;

    const deletingToast = toast.loading('Deleting project...');
    try {
      await projectsApi.delete(id);
      toast.success('Project deleted successfully', { id: deletingToast });
      loadProjects();
    } catch (error) {
      toast.error('Failed to delete project', { id: deletingToast });
    }
  };

  const logout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  const filteredAndSortedProjects = projects
    .filter(project => {
      if (!searchTerm) return true;
      return project.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
             project.description?.toLowerCase().includes(searchTerm.toLowerCase());
    })
    .filter(project => {
      switch (filterBy) {
        case 'recent':
          return new Date(project.created_at) > new Date(Date.now() - 7 * 24 * 60 * 60 * 1000);
        case 'starred':
          return false; // TODO: Implement starring
        default:
          return true;
      }
    })
    .sort((a, b) => {
      switch (sortBy) {
        case 'name':
          return a.name.localeCompare(b.name);
        case 'date':
          return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
        case 'updated':
          return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
        default:
          return 0;
      }
    });

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffInHours = (now.getTime() - date.getTime()) / (1000 * 60 * 60);
    
    if (diffInHours < 24) {
      return `${Math.floor(diffInHours)} hours ago`;
    } else if (diffInHours < 48) {
      return 'Yesterday';
    } else {
      return date.toLocaleDateString();
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-orange-50 via-white to-orange-50/30 flex items-center justify-center">
        <div className="text-center space-y-4">
          <div className="w-16 h-16 bg-orange-500/20 backdrop-blur-sm rounded-2xl flex items-center justify-center mx-auto animate-pulse">
            <Code size={24} className="text-orange-600" />
          </div>
          <div className="space-y-2">
            <p className="text-gray-600 font-medium">Loading your projects...</p>
            <div className="w-32 h-1 bg-orange-200 rounded-full mx-auto overflow-hidden">
              <div className="w-full h-full bg-orange-500 rounded-full animate-pulse"></div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-orange-50 via-white to-orange-50/30">
      {/* Header */}
      <div className="bg-white/80 backdrop-blur-lg border-b border-orange-200/30 shadow-sm sticky top-0 z-10">
        <div className="container mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 bg-orange-500/90 backdrop-blur-sm rounded-xl flex items-center justify-center shadow-lg ring-1 ring-orange-200/50">
                <Code size={20} className="text-white" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-gray-800">Project Studio</h1>
                <p className="text-sm text-gray-600">{projects.length} projects</p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              {/* Search */}
              <div className="relative">
                <Search size={18} className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" />
                <input
                  type="text"
                  placeholder="Search projects..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="pl-10 pr-4 py-2 bg-white/90 backdrop-blur-sm border border-orange-200/50 rounded-xl focus:outline-none focus:ring-2 focus:ring-orange-400/50 text-sm"
                />
              </div>

              {/* Filters */}
              <select 
                value={filterBy} 
                onChange={(e) => setFilterBy(e.target.value as any)}
                className="px-3 py-2 bg-white/90 backdrop-blur-sm border border-orange-200/50 rounded-xl focus:outline-none focus:ring-2 focus:ring-orange-400/50 text-sm"
              >
                <option value="all">All Projects</option>
                <option value="recent">Recent</option>
                <option value="starred">Starred</option>
              </select>

              {/* Sort */}
              <select 
                value={sortBy} 
                onChange={(e) => setSortBy(e.target.value as any)}
                className="px-3 py-2 bg-white/90 backdrop-blur-sm border border-orange-200/50 rounded-xl focus:outline-none focus:ring-2 focus:ring-orange-400/50 text-sm"
              >
                <option value="updated">Last Updated</option>
                <option value="name">Name</option>
                <option value="date">Date Created</option>
              </select>

              {/* View Toggle */}
              <div className="flex bg-white/80 backdrop-blur-sm rounded-xl border border-orange-200/30 p-1">
                <button
                  onClick={() => setViewMode('grid')}
                  className={`p-2 rounded-lg transition-all ${viewMode === 'grid' ? 'bg-orange-500/90 text-white shadow-md' : 'text-gray-600 hover:text-orange-600'}`}
                >
                  <Grid3X3 size={16} />
                </button>
                <button
                  onClick={() => setViewMode('list')}
                  className={`p-2 rounded-lg transition-all ${viewMode === 'list' ? 'bg-orange-500/90 text-white shadow-md' : 'text-gray-600 hover:text-orange-600'}`}
                >
                  <List size={16} />
                </button>
              </div>

              <button
                onClick={logout}
                className="flex items-center gap-2 px-4 py-2 bg-white/80 backdrop-blur-sm border border-orange-200/50 rounded-xl hover:bg-orange-50 text-gray-700 hover:text-orange-700 transition-all"
              >
                <LogOut size={18} />
                <span className="text-sm font-medium">Logout</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="container mx-auto px-6 py-8">
        {/* Stats Cards */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
          <div className="bg-white/80 backdrop-blur-lg rounded-2xl p-4 shadow-lg ring-1 ring-orange-200/30">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600">Total Projects</p>
                <p className="text-2xl font-bold text-gray-800">{projects.length}</p>
              </div>
              <div className="w-12 h-12 bg-blue-100/80 rounded-xl flex items-center justify-center">
                <Folder size={20} className="text-blue-600" />
              </div>
            </div>
          </div>

          <div className="bg-white/80 backdrop-blur-lg rounded-2xl p-4 shadow-lg ring-1 ring-orange-200/30">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600">Active Today</p>
                <p className="text-2xl font-bold text-gray-800">3</p>
              </div>
              <div className="w-12 h-12 bg-green-100/80 rounded-xl flex items-center justify-center">
                <Activity size={20} className="text-green-600" />
              </div>
            </div>
          </div>

          <div className="bg-white/80 backdrop-blur-lg rounded-2xl p-4 shadow-lg ring-1 ring-orange-200/30">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600">Lines of Code</p>
                <p className="text-2xl font-bold text-gray-800">12.4k</p>
              </div>
              <div className="w-12 h-12 bg-purple-100/80 rounded-xl flex items-center justify-center">
                <Code size={20} className="text-purple-600" />
              </div>
            </div>
          </div>

          <div className="bg-white/80 backdrop-blur-lg rounded-2xl p-4 shadow-lg ring-1 ring-orange-200/30">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600">Deployed</p>
                <p className="text-2xl font-bold text-gray-800">7</p>
              </div>
              <div className="w-12 h-12 bg-orange-100/80 rounded-xl flex items-center justify-center">
                <Zap size={20} className="text-orange-600" />
              </div>
            </div>
          </div>
        </div>

        {/* Projects Grid/List */}
        {viewMode === 'grid' ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
            {/* Create New Project Card */}
            <button
              onClick={() => setShowCreateModal(true)}
              className="group bg-white/60 backdrop-blur-lg p-6 rounded-2xl shadow-lg ring-1 ring-orange-200/30 hover:shadow-xl hover:scale-105 transition-all duration-300 border-2 border-dashed border-orange-300/50 hover:border-orange-400/70 min-h-[240px] flex flex-col items-center justify-center gap-4"
            >
              <div className="w-16 h-16 bg-orange-100/80 backdrop-blur-sm rounded-2xl flex items-center justify-center group-hover:bg-orange-200/80 transition-colors">
                <Plus size={24} className="text-orange-600" />
              </div>
              <div className="text-center">
                <h3 className="text-lg font-semibold text-gray-800 mb-2">Create New Project</h3>
                <p className="text-sm text-gray-600">Start building something amazing</p>
              </div>
            </button>

            {/* Project Cards */}
            {filteredAndSortedProjects.map((project) => (
              <div
                key={project.id}
                className="group bg-white/80 backdrop-blur-lg p-6 rounded-2xl shadow-lg ring-1 ring-orange-200/30 hover:shadow-xl hover:scale-105 transition-all duration-300 relative min-h-[240px] flex flex-col"
              >
                <div className="flex items-start justify-between mb-4">
                  <div className="w-12 h-12 bg-blue-100/80 backdrop-blur-sm rounded-xl flex items-center justify-center">
                    <FolderOpen size={20} className="text-blue-600" />
                  </div>
                  <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={() => deleteProject(project.id)}
                      className="p-2 hover:bg-red-100/80 rounded-lg text-red-500 hover:text-red-700 transition-colors"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </div>

                <div className="flex-1">
                  <h3 className="text-lg font-semibold text-gray-800 mb-2 truncate">{project.name}</h3>
                  <p className="text-sm text-gray-600 mb-4 line-clamp-2">
                    {project.description || 'No description provided'}
                  </p>
                </div>

                <div className="space-y-3">
                  <div className="flex items-center text-xs text-gray-500 gap-4">
                    <div className="flex items-center gap-1">
                      <Calendar size={12} />
                      <span>{formatDate(project.created_at)}</span>
                    </div>
                    <div className="flex items-center gap-1">
                      <Clock size={12} />
                      <span>{formatDate(project.updated_at)}</span>
                    </div>
                  </div>

                  <button
                    onClick={() => navigate(`/project/${project.id}`)}
                    className="w-full bg-orange-500/90 hover:bg-orange-600/90 text-white px-4 py-2.5 rounded-xl font-medium transition-all hover:shadow-lg hover:scale-105 backdrop-blur-sm"
                  >
                    Open Project
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          // List View
          <div className="bg-white/80 backdrop-blur-lg rounded-2xl shadow-lg ring-1 ring-orange-200/30 overflow-hidden">
            <div className="p-4 border-b border-orange-200/30">
              <h3 className="text-lg font-semibold text-gray-800">Projects</h3>
            </div>
            <div className="divide-y divide-orange-200/30">
              {filteredAndSortedProjects.map((project) => (
                <div key={project.id} className="p-4 hover:bg-orange-50/50 transition-colors group">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                      <div className="w-10 h-10 bg-blue-100/80 backdrop-blur-sm rounded-lg flex items-center justify-center">
                        <FolderOpen size={18} className="text-blue-600" />
                      </div>
                      <div>
                        <h4 className="font-medium text-gray-800">{project.name}</h4>
                        <p className="text-sm text-gray-600 truncate max-w-md">
                          {project.description || 'No description'}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-4">
                      <div className="text-xs text-gray-500">
                        <div>Created {formatDate(project.created_at)}</div>
                        <div>Updated {formatDate(project.updated_at)}</div>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => navigate(`/project/${project.id}`)}
                          className="px-4 py-2 bg-orange-500/90 text-white rounded-lg hover:bg-orange-600/90 transition-colors text-sm font-medium"
                        >
                          Open
                        </button>
                        <button
                          onClick={() => deleteProject(project.id)}
                          className="p-2 text-red-500 hover:bg-red-100/80 rounded-lg transition-colors opacity-0 group-hover:opacity-100"
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {filteredAndSortedProjects.length === 0 && searchTerm && (
          <div className="text-center py-12">
            <div className="w-16 h-16 bg-gray-100/80 backdrop-blur-sm rounded-2xl flex items-center justify-center mx-auto mb-4">
              <Search size={24} className="text-gray-400" />
            </div>
            <h3 className="text-lg font-medium text-gray-700 mb-2">No projects found</h3>
            <p className="text-gray-500">Try adjusting your search or filters</p>
          </div>
        )}
      </div>

      {/* Create Project Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-white/95 backdrop-blur-lg p-8 rounded-3xl w-full max-w-md shadow-2xl ring-1 ring-orange-200/50 relative">
            <div className="text-center mb-6">
              <div className="w-16 h-16 bg-orange-100/80 backdrop-blur-sm rounded-2xl flex items-center justify-center mx-auto mb-4">
                <Plus size={24} className="text-orange-600" />
              </div>
              <h2 className="text-2xl font-bold text-gray-800 mb-2">Create New Project</h2>
              <p className="text-gray-600">Let's build something incredible together</p>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Project Name</label>
                <input
                  type="text"
                  value={newProject.name}
                  onChange={(e) => setNewProject({ ...newProject, name: e.target.value })}
                  className="w-full bg-white/90 backdrop-blur-sm text-gray-800 px-4 py-3 rounded-xl border border-orange-200/50 focus:outline-none focus:ring-2 focus:ring-orange-400/50 placeholder-gray-500"
                  placeholder="My Awesome App"
                  disabled={isCreating}
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Description</label>
                <textarea
                  value={newProject.description}
                  onChange={(e) => setNewProject({ ...newProject, description: e.target.value })}
                  className="w-full bg-white/90 backdrop-blur-sm text-gray-800 px-4 py-3 rounded-xl border border-orange-200/50 focus:outline-none focus:ring-2 focus:ring-orange-400/50 placeholder-gray-500 resize-none"
                  rows={3}
                  placeholder="Describe your project..."
                  disabled={isCreating}
                />
              </div>

              <div className="flex gap-3 pt-4">
                <button
                  onClick={createProject}
                  disabled={isCreating || !newProject.name.trim()}
                  className="flex-1 bg-orange-500/90 hover:bg-orange-600/90 disabled:bg-gray-300 disabled:cursor-not-allowed text-white py-3 rounded-xl font-medium transition-all hover:shadow-lg hover:scale-105 backdrop-blur-sm"
                >
                  {isCreating ? 'Creating...' : 'Create Project'}
                </button>
                <button
                  onClick={() => setShowCreateModal(false)}
                  disabled={isCreating}
                  className="flex-1 bg-white/90 backdrop-blur-sm border border-orange-200/50 text-gray-700 py-3 rounded-xl font-medium hover:bg-orange-50 transition-all disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}