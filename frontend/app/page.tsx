'use client';

import { useState, useMemo, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { AlertCircle, DollarSign, TrendingDown, Server, HardDrive, Database, Cloud, Activity, ArrowUpDown, ChevronUp, ChevronDown, Sparkles, Lightbulb, LogOut, Plus, Trash2, Key } from 'lucide-react';
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import ChatPanel from './components/ChatPanel';
import { useAuth } from './context/AuthContext';
import { apiGet, apiPost, apiPatch, apiDelete } from './lib/api';

interface AnalysisResult {
  provider?: string;
  monthly_cost: {
    total_cost: number;
    projected_cost?: number;
    days_elapsed?: number;
    days_in_month?: number;
    currency: string;
    period: string;
  };
  daily_costs?: Array<{ date: string; cost: number }>;
  daily_costs_by_service?: Array<{ date: string; cost: number; service: string }>;
  top_services: Array<{ service: string; cost: number }>;
  resource_costs?: Array<{
    resource_id: string;
    resource_type: string;
    service: string;
    cost: number;
    name?: string;
  }>;
  savings_opportunities: {
    total_potential_savings: number;
    idle_ec2_instances: {
      count: number;
      potential_savings: number;
      items: Array<{
        instance_id: string;
        instance_type: string;
        estimated_monthly_cost: number;
        recommendation?: string;
        avg_cpu?: number;
        max_cpu?: number;
        avg_network_in?: number;
        avg_network_out?: number;
      }>;
    };
    unattached_ebs_volumes: {
      count: number;
      potential_savings: number;
      items: Array<{ volume_id: string; size_gb: number; estimated_monthly_cost: number }>;
    };
    old_snapshots: {
      count: number;
      potential_savings: number;
      items: Array<{ snapshot_id: string; age_days: number; estimated_monthly_cost: number }>;
    };
  };
  anomalies?: Array<{
    date: string;
    service: string;
    expected_cost: number;
    actual_cost: number;
    impact: number;
    impact_percentage: number;
    severity: string;
    source: string;
    description: string;
  }>;
  recommendations?: AIRecommendations | null;
}

interface Recommendation {
  title: string;
  category: string;
  priority: string;
  estimated_monthly_savings: number;
  effort: string;
  description: string;
  affected_resources: string[];
}

interface AIRecommendations {
  summary: string;
  total_estimated_monthly_savings: number;
  recommendations: Recommendation[];
}

interface SavedCredential {
  id: string;
  provider: string;
  label: string;
  region: string | null;
  created_at: string;
}

type Provider = 'aws' | 'gcp' | 'azure';
type SortField = 'cost' | 'resource_id' | 'resource_type' | 'name';

const PROVIDERS: { id: Provider; name: string; available: boolean }[] = [
  { id: 'aws', name: 'Amazon Web Services', available: true },
  { id: 'gcp', name: 'Google Cloud Platform', available: true },
  { id: 'azure', name: 'Microsoft Azure', available: true },
];

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'bg-red-100 text-red-800 border-red-300',
  high: 'bg-orange-100 text-orange-800 border-orange-300',
  medium: 'bg-yellow-100 text-yellow-800 border-yellow-300',
  low: 'bg-blue-100 text-blue-800 border-blue-300',
};

const PRIORITY_STYLES: Record<string, string> = {
  critical: 'border-l-red-500',
  high: 'border-l-orange-500',
  medium: 'border-l-yellow-500',
  low: 'border-l-blue-400',
};

const EFFORT_LABELS: Record<string, { label: string; color: string }> = {
  'quick-win': { label: 'Quick Win', color: 'bg-green-100 text-green-800' },
  'moderate': { label: 'Moderate', color: 'bg-yellow-100 text-yellow-800' },
  'significant': { label: 'Significant', color: 'bg-red-100 text-red-800' },
};

const SERVICE_COLORS = [
  '#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6',
  '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1',
];

const SHORT_SERVICE_NAMES: Record<string, string> = {
  'Amazon Elastic Compute Cloud': 'EC2',
  'Amazon Relational Database Service': 'RDS',
  'Amazon Simple Storage Service': 'S3',
  'AWS Lambda': 'Lambda',
  'Amazon CloudFront': 'CloudFront',
  'Amazon DynamoDB': 'DynamoDB',
  'Amazon Elastic Load Balancing': 'ELB',
  'Amazon ElastiCache': 'ElastiCache',
  'AWS Key Management Service': 'KMS',
  'Amazon Route 53': 'Route 53',
};

function shortName(service: string) {
  return SHORT_SERVICE_NAMES[service] || service;
}

export default function Home() {
  const { token, username, loading: authLoading, logout } = useAuth();
  const router = useRouter();

  // Redirect to login if not authenticated
  useEffect(() => {
    if (!authLoading && !token) {
      router.push('/login');
    }
  }, [authLoading, token, router]);

  const [provider, setProvider] = useState<Provider>('aws');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState('');
  const [isDemo, setIsDemo] = useState(false);
  const [resourceSort, setResourceSort] = useState<{ field: SortField; asc: boolean }>({ field: 'cost', asc: false });

  // Credential management
  const [savedCreds, setSavedCreds] = useState<SavedCredential[]>([]);
  const [selectedCredId, setSelectedCredId] = useState<string>('');
  const [showAddCred, setShowAddCred] = useState(false);
  const [newCredLabel, setNewCredLabel] = useState('');
  const [newCredAccessKey, setNewCredAccessKey] = useState('');
  const [newCredSecretKey, setNewCredSecretKey] = useState('');
  const [newCredSessionToken, setNewCredSessionToken] = useState('');
  const [newCredRegion, setNewCredRegion] = useState('us-east-1');
  const [credError, setCredError] = useState('');
  const [credLoading, setCredLoading] = useState(false);
  const [showRefreshToken, setShowRefreshToken] = useState(false);
  const [refreshToken, setRefreshToken] = useState('');
  const [refreshLoading, setRefreshLoading] = useState(false);

  // Load saved credentials on mount
  useEffect(() => {
    if (token) {
      loadCredentials();
    }
  }, [token]);

  const loadCredentials = async () => {
    try {
      const data = await apiGet('/api/credentials');
      setSavedCreds(data);
      if (data.length > 0 && !selectedCredId) {
        setSelectedCredId(data[0].id);
      }
    } catch {
      // Silently fail – user may not have any creds yet
    }
  };

  const handleSaveCredential = async () => {
    setCredError('');
    if (!newCredLabel || !newCredAccessKey || !newCredSecretKey) {
      setCredError('All fields are required');
      return;
    }
    setCredLoading(true);
    try {
      const credentials: Record<string, string> = {
        access_key: newCredAccessKey,
        secret_key: newCredSecretKey,
      };
      if (newCredSessionToken.trim()) {
        credentials.session_token = newCredSessionToken.trim();
      }
      const saved = await apiPost('/api/credentials', {
        provider,
        label: newCredLabel,
        credentials,
        region: newCredRegion,
      });
      setSavedCreds(prev => [saved, ...prev]);
      setSelectedCredId(saved.id);
      setShowAddCred(false);
      setNewCredLabel('');
      setNewCredAccessKey('');
      setNewCredSecretKey('');
      setNewCredSessionToken('');
      setNewCredRegion('us-east-1');
    } catch (err) {
      setCredError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setCredLoading(false);
    }
  };

  const handleDeleteCredential = async (id: string) => {
    try {
      await apiDelete(`/api/credentials/${id}`);
      setSavedCreds(prev => prev.filter(c => c.id !== id));
      if (selectedCredId === id) {
        setSelectedCredId(savedCreds.find(c => c.id !== id)?.id || '');
      }
    } catch {
      // ignore
    }
  };

  const handleRefreshToken = async () => {
    if (!refreshToken.trim() || !selectedCredId) return;
    setRefreshLoading(true);
    setCredError('');
    try {
      await apiPatch(`/api/credentials/${selectedCredId}`, {
        credentials: { session_token: refreshToken.trim() },
      });
      setRefreshToken('');
      setShowRefreshToken(false);
    } catch (err) {
      setCredError(err instanceof Error ? err.message : 'Failed to update token');
    } finally {
      setRefreshLoading(false);
    }
  };

  const handleDemo = async () => {
    setLoading(true);
    setError('');
    setResult(null);
    setIsDemo(true);

    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/demo`);
      if (!response.ok) throw new Error('Failed to load demo data');
      const data = await response.json();
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  const handleAnalyze = async () => {
    if (!selectedCredId) {
      setError('Please select or add a credential first');
      return;
    }
    setLoading(true);
    setError('');
    setResult(null);
    setIsDemo(false);

    try {
      const data = await apiPost('/api/analyze/detailed', {
        credential_id: selectedCredId,
      });
      setResult(data);
    } catch (err) {
      if (err instanceof Error && err.message === 'Unauthorized') return; // redirect handled by api helper
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  // Build stacked bar chart data from daily_costs_by_service
  const serviceChartData = useMemo(() => {
    if (!result?.daily_costs_by_service) return { data: [], services: [] as string[] };
    const dateMap: Record<string, Record<string, number>> = {};
    const serviceSet = new Set<string>();
    for (const d of result.daily_costs_by_service) {
      const svc = shortName(d.service);
      serviceSet.add(svc);
      if (!dateMap[d.date]) dateMap[d.date] = {};
      dateMap[d.date][svc] = (dateMap[d.date][svc] || 0) + d.cost;
    }
    const services = Array.from(serviceSet);
    const data = Object.keys(dateMap).sort().map(date => ({
      date: date.slice(5),
      ...dateMap[date],
    }));
    return { data, services };
  }, [result?.daily_costs_by_service]);

  const sortedResources = useMemo(() => {
    if (!result?.resource_costs) return [];
    const sorted = [...result.resource_costs];
    sorted.sort((a, b) => {
      const field = resourceSort.field;
      const aVal = a[field] ?? '';
      const bVal = b[field] ?? '';
      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return resourceSort.asc ? aVal - bVal : bVal - aVal;
      }
      return resourceSort.asc
        ? String(aVal).localeCompare(String(bVal))
        : String(bVal).localeCompare(String(aVal));
    });
    return sorted;
  }, [result?.resource_costs, resourceSort]);

  const toggleSort = (field: SortField) => {
    setResourceSort(prev =>
      prev.field === field ? { field, asc: !prev.asc } : { field, asc: false }
    );
  };

  const SortIcon = ({ field }: { field: SortField }) => {
    if (resourceSort.field !== field) return <ArrowUpDown size={14} className="text-gray-400" />;
    return resourceSort.asc ? <ChevronUp size={14} /> : <ChevronDown size={14} />;
  };

  const anomalyCount = result?.anomalies?.length || 0;
  const recCount = result?.recommendations?.recommendations?.length || 0;
  const ruleSavings = result?.savings_opportunities.total_potential_savings || 0;
  const aiSavings = result?.recommendations?.total_estimated_monthly_savings || 0;
  const totalSavings = Math.max(ruleSavings, aiSavings);
  const issueCount = (result?.savings_opportunities.idle_ec2_instances.count || 0) +
    (result?.savings_opportunities.unattached_ebs_volumes.count || 0) +
    (result?.savings_opportunities.old_snapshots.count || 0) +
    anomalyCount + recCount;

  // Show nothing while checking auth
  if (authLoading || !token) {
    return null;
  }

  return (
    <main className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header with user info */}
        <div className="flex items-center justify-between mb-2">
          <h1 className="text-4xl font-bold text-gray-900">Cloud Cost Optimizer</h1>
          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-600">Signed in as <strong>{username}</strong></span>
            <button
              onClick={logout}
              className="flex items-center gap-1 text-sm text-gray-500 hover:text-red-600 transition"
            >
              <LogOut size={16} /> Logout
            </button>
          </div>
        </div>
        <p className="text-gray-600 mb-8">
          Analyze your cloud spending and discover savings opportunities
        </p>

        {/* Input Form */}
        <div className="bg-white rounded-lg shadow-md p-6 mb-8">
          {/* Provider Selector */}
          <div className="mb-6">
            <h2 className="text-xl font-semibold mb-3 flex items-center gap-2">
              <Cloud size={20} />
              Cloud Provider
            </h2>
            <div className="flex gap-3">
              {PROVIDERS.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setProvider(p.id)}
                  disabled={!p.available}
                  className={`px-4 py-2 rounded-lg text-sm font-medium transition border ${
                    provider === p.id
                      ? 'bg-blue-600 text-white border-blue-600'
                      : p.available
                        ? 'bg-white text-gray-700 border-gray-300 hover:border-blue-400'
                        : 'bg-gray-100 text-gray-400 border-gray-200 cursor-not-allowed'
                  }`}
                >
                  {p.name}
                  {!p.available && <span className="ml-1 text-xs">(Coming Soon)</span>}
                </button>
              ))}
            </div>
          </div>

          {/* Credential Selector */}
          <div className="mb-4">
            <h3 className="text-lg font-medium mb-3 flex items-center gap-2">
              <Key size={18} />
              Credentials
            </h3>

            {savedCreds.length > 0 && (
              <div className="flex items-center gap-3 mb-3">
                <select
                  value={selectedCredId}
                  onChange={e => setSelectedCredId(e.target.value)}
                  className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-gray-900 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="">Select a saved credential...</option>
                  {savedCreds.map(c => (
                    <option key={c.id} value={c.id}>
                      {c.label} ({c.provider.toUpperCase()}{c.region ? ` - ${c.region}` : ''})
                    </option>
                  ))}
                </select>
                {selectedCredId && (
                  <>
                    <button
                      onClick={() => { setShowRefreshToken(!showRefreshToken); setCredError(''); setRefreshToken(''); }}
                      className="px-3 py-2 text-sm text-amber-600 border border-amber-300 hover:bg-amber-50 rounded-lg transition whitespace-nowrap"
                      title="Update session token for temporary credentials"
                    >
                      Refresh Token
                    </button>
                    <button
                      onClick={() => handleDeleteCredential(selectedCredId)}
                      className="p-2 text-red-500 hover:bg-red-50 rounded-lg transition"
                      title="Delete this credential"
                    >
                      <Trash2 size={18} />
                    </button>
                  </>
                )}
              </div>
            )}

            {/* Inline Refresh Token Panel */}
            {showRefreshToken && selectedCredId && (
              <div className="mb-3 p-3 bg-amber-50 rounded-lg border border-amber-200">
                <p className="text-xs text-amber-700 mb-2 font-medium">Paste your new session token below (STS tokens expire — refresh when you get a new one)</p>
                <textarea
                  value={refreshToken}
                  onChange={e => setRefreshToken(e.target.value)}
                  rows={3}
                  className="w-full px-3 py-2 border border-amber-300 rounded-lg text-gray-900 text-xs font-mono placeholder:text-gray-400 focus:ring-2 focus:ring-amber-400 focus:border-transparent resize-none"
                  placeholder="IQoJb3Jp..."
                />
                {credError && <p className="text-xs text-red-600 mt-1">{credError}</p>}
                <div className="flex gap-2 mt-2">
                  <button
                    onClick={handleRefreshToken}
                    disabled={refreshLoading || !refreshToken.trim()}
                    className="px-3 py-1.5 bg-amber-600 text-white rounded-lg text-sm font-medium hover:bg-amber-700 disabled:bg-gray-400 transition"
                  >
                    {refreshLoading ? 'Saving...' : 'Update Token'}
                  </button>
                  <button
                    onClick={() => { setShowRefreshToken(false); setRefreshToken(''); setCredError(''); }}
                    className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 transition"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            <button
              onClick={() => setShowAddCred(!showAddCred)}
              className="flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800 transition"
            >
              <Plus size={16} /> {showAddCred ? 'Cancel' : 'Add New Credentials'}
            </button>

            {/* Inline Add Credential Form */}
            {showAddCred && (
              <div className="mt-3 p-4 bg-gray-50 rounded-lg border border-gray-200">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Label</label>
                    <input
                      type="text"
                      value={newCredLabel}
                      onChange={e => setNewCredLabel(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg text-gray-900 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      placeholder="e.g. Production AWS"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Region</label>
                    <input
                      type="text"
                      value={newCredRegion}
                      onChange={e => setNewCredRegion(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg text-gray-900 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      placeholder="us-east-1"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Access Key</label>
                    <input
                      type="text"
                      value={newCredAccessKey}
                      onChange={e => setNewCredAccessKey(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg text-gray-900 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      placeholder="AKIA..."
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Secret Key</label>
                    <input
                      type="password"
                      value={newCredSecretKey}
                      onChange={e => setNewCredSecretKey(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg text-gray-900 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      placeholder="********"
                    />
                  </div>
                  <div className="md:col-span-2">
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Session Token <span className="text-gray-400 font-normal">(optional — required for temporary credentials)</span>
                    </label>
                    <input
                      type="password"
                      value={newCredSessionToken}
                      onChange={e => setNewCredSessionToken(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg text-gray-900 placeholder:text-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      placeholder="Paste session token if using temporary credentials (ASIA...)"
                    />
                  </div>
                </div>
                {credError && (
                  <p className="text-sm text-red-600 mb-2">{credError}</p>
                )}
                <button
                  onClick={handleSaveCredential}
                  disabled={credLoading}
                  className="px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 disabled:bg-gray-400 transition"
                >
                  {credLoading ? 'Saving...' : 'Save Credential'}
                </button>
              </div>
            )}
          </div>

          <div className="flex gap-3">
            <button
              onClick={handleAnalyze}
              disabled={loading || !selectedCredId}
              className="w-full md:w-auto px-6 py-3 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition"
            >
              {loading ? 'Analyzing...' : 'Analyze Costs'}
            </button>
            <button
              onClick={handleDemo}
              disabled={loading}
              className="w-full md:w-auto px-6 py-3 bg-gray-700 text-white rounded-lg font-medium hover:bg-gray-800 disabled:bg-gray-400 disabled:cursor-not-allowed transition"
            >
              {loading ? 'Loading...' : 'Try Demo'}
            </button>
          </div>
        </div>

        {/* Error Message */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-8 flex items-start">
            <AlertCircle className="text-red-500 mr-3 flex-shrink-0" size={20} />
            <p className="text-red-700">{error}</p>
          </div>
        )}

        {/* Results */}
        {result && (
          <>
            {/* Summary Cards */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
              <div className="bg-white rounded-lg shadow-md p-6">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-sm font-medium text-gray-600">Monthly Spend</h3>
                  <DollarSign className="text-blue-500" size={20} />
                </div>
                <p className="text-3xl font-bold text-gray-900">
                  ${result.monthly_cost.total_cost.toLocaleString()}
                </p>
                <p className="text-xs text-gray-500 mt-1">
                  {result.monthly_cost.period} (MTD)
                </p>
                {result.monthly_cost.projected_cost && (
                  <p className="text-sm font-semibold text-blue-600 mt-1">
                    ~${result.monthly_cost.projected_cost.toLocaleString()} projected
                    <span className="text-xs text-gray-400 font-normal ml-1">
                      ({result.monthly_cost.days_elapsed}/{result.monthly_cost.days_in_month} days)
                    </span>
                  </p>
                )}
              </div>

              <div className="bg-white rounded-lg shadow-md p-6">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-sm font-medium text-gray-600">Potential Savings</h3>
                  <TrendingDown className="text-green-500" size={20} />
                </div>
                <p className="text-3xl font-bold text-green-600">
                  ${totalSavings.toLocaleString()}/mo
                </p>
                <p className="text-xs text-gray-500 mt-1">
                  {(result.monthly_cost.projected_cost || result.monthly_cost.total_cost) > 0
                    ? ((totalSavings / (result.monthly_cost.projected_cost || result.monthly_cost.total_cost)) * 100).toFixed(1)
                    : '0'}% of projected spend
                  {aiSavings > 0 && ruleSavings === 0 && ' (AI estimate)'}
                </p>
              </div>

              <div className="bg-white rounded-lg shadow-md p-6">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-sm font-medium text-gray-600">Issues Found</h3>
                  <AlertCircle className="text-orange-500" size={20} />
                </div>
                <p className="text-3xl font-bold text-gray-900">
                  {issueCount}
                </p>
                <p className="text-xs text-gray-500 mt-1">
                  {recCount > 0 ? `${recCount} recommendations` : 'Across all categories'}
                  {anomalyCount > 0 ? `, ${anomalyCount} anomalies` : ''}
                </p>
              </div>

              <div className="bg-white rounded-lg shadow-md p-6">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-sm font-medium text-gray-600">Anomalies</h3>
                  <Activity className="text-red-500" size={20} />
                </div>
                <p className="text-3xl font-bold text-red-600">
                  {anomalyCount}
                </p>
                <p className="text-xs text-gray-500 mt-1">
                  {anomalyCount > 0
                    ? `${result.anomalies!.filter(a => a.severity === 'critical' || a.severity === 'high').length} high/critical`
                    : 'No anomalies detected'}
                </p>
              </div>
            </div>

            {/* Daily Cost Trend Chart */}
            {result.daily_costs && result.daily_costs.length > 0 && (
              <div className="bg-white rounded-lg shadow-md p-6 mb-8">
                <h2 className="text-xl font-semibold mb-4">30-Day Cost Trend</h2>
                <ResponsiveContainer width="100%" height={300}>
                  <AreaChart data={result.daily_costs.map(d => ({ ...d, date: d.date.slice(5) }))}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                    <YAxis tick={{ fontSize: 12 }} tickFormatter={(v) => `$${v}`} />
                    <Tooltip formatter={(value) => [`$${Number(value).toFixed(2)}`, 'Daily Cost']} />
                    <Area type="monotone" dataKey="cost" stroke="#3b82f6" fill="#93c5fd" fillOpacity={0.4} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Service Breakdown Stacked Bar Chart */}
            {serviceChartData.data.length > 0 && (
              <div className="bg-white rounded-lg shadow-md p-6 mb-8">
                <h2 className="text-xl font-semibold mb-4">Daily Cost by Service</h2>
                <ResponsiveContainer width="100%" height={350}>
                  <BarChart data={serviceChartData.data}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                    <YAxis tick={{ fontSize: 12 }} tickFormatter={(v) => `$${v}`} />
                    <Tooltip formatter={(value) => `$${Number(value).toFixed(2)}`} />
                    <Legend />
                    {serviceChartData.services.map((svc, i) => (
                      <Bar key={svc} dataKey={svc} stackId="a" fill={SERVICE_COLORS[i % SERVICE_COLORS.length]} />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Top Services */}
            <div className="bg-white rounded-lg shadow-md p-6 mb-8">
              <h2 className="text-xl font-semibold mb-4">Top 10 Cost Drivers</h2>
              <div className="space-y-3">
                {result.top_services.map((service, index) => (
                  <div key={index} className="flex items-center justify-between">
                    <div className="flex-1">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-sm font-medium text-gray-700">{service.service}</span>
                        <span className="text-sm font-bold text-gray-900">${service.cost.toLocaleString()}</span>
                      </div>
                      <div className="w-full bg-gray-200 rounded-full h-2">
                        <div
                          className="bg-blue-500 h-2 rounded-full"
                          style={{
                            width: `${(service.cost / result.top_services[0].cost) * 100}%`
                          }}
                        />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Resource Cost Table */}
            {sortedResources.length > 0 && (
              <div className="bg-white rounded-lg shadow-md p-6 mb-8">
                <h2 className="text-xl font-semibold mb-4">Resource Costs</h2>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-200">
                        <th className="text-left py-3 px-2 font-medium text-gray-600 cursor-pointer select-none" onClick={() => toggleSort('name')}>
                          <span className="flex items-center gap-1">Name <SortIcon field="name" /></span>
                        </th>
                        <th className="text-left py-3 px-2 font-medium text-gray-600 cursor-pointer select-none" onClick={() => toggleSort('resource_id')}>
                          <span className="flex items-center gap-1">Resource ID <SortIcon field="resource_id" /></span>
                        </th>
                        <th className="text-left py-3 px-2 font-medium text-gray-600 cursor-pointer select-none" onClick={() => toggleSort('resource_type')}>
                          <span className="flex items-center gap-1">Type <SortIcon field="resource_type" /></span>
                        </th>
                        <th className="text-right py-3 px-2 font-medium text-gray-600 cursor-pointer select-none" onClick={() => toggleSort('cost')}>
                          <span className="flex items-center gap-1 justify-end">Cost (30d) <SortIcon field="cost" /></span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedResources.map((r, i) => (
                        <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                          <td className="py-2 px-2 font-medium text-gray-900">{r.name || '-'}</td>
                          <td className="py-2 px-2 text-gray-600 font-mono text-xs">{r.resource_id}</td>
                          <td className="py-2 px-2">
                            <span className="inline-block px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-700 uppercase">
                              {r.resource_type}
                            </span>
                          </td>
                          <td className="py-2 px-2 text-right font-bold text-gray-900">${r.cost.toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Anomalies Section */}
            {result.anomalies && result.anomalies.length > 0 && (
              <div className="bg-white rounded-lg shadow-md p-6 mb-8">
                <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
                  <Activity size={20} className="text-red-500" />
                  Cost Anomalies
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {result.anomalies.map((anomaly, i) => (
                    <div key={i} className={`rounded-lg border p-4 ${SEVERITY_COLORS[anomaly.severity] || 'bg-gray-100 text-gray-800 border-gray-300'}`}>
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-xs font-bold uppercase">{anomaly.severity}</span>
                        <span className="text-xs opacity-75">{anomaly.date}</span>
                      </div>
                      <p className="font-semibold text-sm mb-1">{shortName(anomaly.service)}</p>
                      <p className="text-xs mb-2">{anomaly.description}</p>
                      <div className="flex items-center justify-between text-xs">
                        <span>Expected: ${anomaly.expected_cost.toFixed(2)}</span>
                        <span>Actual: ${anomaly.actual_cost.toFixed(2)}</span>
                        <span className="font-bold">+${anomaly.impact.toFixed(2)} ({anomaly.impact_percentage.toFixed(0)}%)</span>
                      </div>
                      <div className="mt-1 text-xs opacity-60">
                        Source: {anomaly.source === 'aws' ? 'AWS Cost Anomaly Detection' : 'Statistical (z-score)'}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* AI Recommendations Section */}
            {result.recommendations && (
              <div className="bg-white rounded-lg shadow-md p-6 mb-8">
                <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
                  <Sparkles size={20} className="text-purple-500" />
                  AI Cost Recommendations
                </h2>

                <div className="bg-purple-50 border border-purple-200 rounded-lg p-4 mb-6">
                  <div className="flex items-start gap-3">
                    <Lightbulb size={20} className="text-purple-600 flex-shrink-0 mt-0.5" />
                    <div>
                      <p className="text-sm text-gray-800">{result.recommendations.summary}</p>
                      <p className="text-lg font-bold text-purple-700 mt-2">
                        Estimated savings: ${result.recommendations.total_estimated_monthly_savings.toLocaleString()}/mo
                      </p>
                    </div>
                  </div>
                </div>

                <div className="space-y-4">
                  {result.recommendations.recommendations.map((rec, i) => {
                    const effort = EFFORT_LABELS[rec.effort] || { label: rec.effort, color: 'bg-gray-100 text-gray-800' };
                    const borderColor = PRIORITY_STYLES[rec.priority] || 'border-l-gray-400';
                    return (
                      <div key={i} className={`border-l-4 ${borderColor} bg-gray-50 rounded-r-lg p-4`}>
                        <div className="flex items-center justify-between mb-2">
                          <h3 className="font-semibold text-gray-900">{rec.title}</h3>
                          <div className="flex items-center gap-2">
                            <span className={`text-xs px-2 py-0.5 rounded font-medium ${effort.color}`}>
                              {effort.label}
                            </span>
                            <span className="text-xs px-2 py-0.5 rounded font-medium bg-gray-200 text-gray-700 uppercase">
                              {rec.category}
                            </span>
                            <span className="text-xs font-bold uppercase text-gray-500">
                              {rec.priority}
                            </span>
                          </div>
                        </div>
                        <p className="text-sm text-gray-700 mb-2">{rec.description}</p>
                        <div className="flex items-center justify-between">
                          {rec.estimated_monthly_savings > 0 && (
                            <span className="text-sm font-bold text-green-600">
                              Save ~${rec.estimated_monthly_savings.toLocaleString()}/mo
                            </span>
                          )}
                          {rec.affected_resources.length > 0 && (
                            <span className="text-xs text-gray-500">
                              Resources: {rec.affected_resources.slice(0, 3).join(', ')}
                              {rec.affected_resources.length > 3 && ` +${rec.affected_resources.length - 3} more`}
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Savings Opportunities */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
              <div className="bg-white rounded-lg shadow-md p-6">
                <div className="flex items-center mb-4">
                  <Server className="text-orange-500 mr-2" size={24} />
                  <h3 className="text-lg font-semibold">Idle Instances</h3>
                </div>
                <p className="text-2xl font-bold text-orange-600 mb-2">
                  ${result.savings_opportunities.idle_ec2_instances.potential_savings}
                </p>
                <p className="text-sm text-gray-600 mb-4">
                  {result.savings_opportunities.idle_ec2_instances.count} instances found
                </p>
                {result.savings_opportunities.idle_ec2_instances.items.slice(0, 5).map((item, i) => (
                  <div key={i} className="mb-3 p-2 bg-orange-50 rounded text-xs">
                    <div className="flex justify-between font-medium text-gray-800 mb-1">
                      <span>{item.instance_id}</span>
                      <span>${item.estimated_monthly_cost}/mo</span>
                    </div>
                    <div className="text-gray-600">{item.instance_type}</div>
                    {item.avg_cpu !== undefined && (
                      <div className="mt-1 flex gap-3 text-gray-500">
                        <span>CPU: <span className={item.avg_cpu < 5 ? 'text-red-600 font-medium' : 'text-green-600'}>{item.avg_cpu}%</span></span>
                        <span>Net: {((item.avg_network_in || 0) + (item.avg_network_out || 0)) / 1_000_000 < 0.01 ? '<0.01' : (((item.avg_network_in || 0) + (item.avg_network_out || 0)) / 1_000_000).toFixed(2)} MB/hr</span>
                      </div>
                    )}
                  </div>
                ))}
              </div>

              <div className="bg-white rounded-lg shadow-md p-6">
                <div className="flex items-center mb-4">
                  <HardDrive className="text-purple-500 mr-2" size={24} />
                  <h3 className="text-lg font-semibold">Unattached Volumes</h3>
                </div>
                <p className="text-2xl font-bold text-purple-600 mb-2">
                  ${result.savings_opportunities.unattached_ebs_volumes.potential_savings}
                </p>
                <p className="text-sm text-gray-600 mb-4">
                  {result.savings_opportunities.unattached_ebs_volumes.count} volumes found
                </p>
                {result.savings_opportunities.unattached_ebs_volumes.items.slice(0, 3).map((item, i) => (
                  <div key={i} className="text-xs text-gray-500 mb-1">
                    &bull; {item.volume_id} ({item.size_gb}GB) - ${item.estimated_monthly_cost}/mo
                  </div>
                ))}
              </div>

              <div className="bg-white rounded-lg shadow-md p-6">
                <div className="flex items-center mb-4">
                  <Database className="text-blue-500 mr-2" size={24} />
                  <h3 className="text-lg font-semibold">Old Snapshots</h3>
                </div>
                <p className="text-2xl font-bold text-blue-600 mb-2">
                  ${result.savings_opportunities.old_snapshots.potential_savings}
                </p>
                <p className="text-sm text-gray-600 mb-4">
                  {result.savings_opportunities.old_snapshots.count} snapshots &gt;90 days
                </p>
                {result.savings_opportunities.old_snapshots.items.slice(0, 3).map((item, i) => (
                  <div key={i} className="text-xs text-gray-500 mb-1">
                    &bull; {item.snapshot_id} ({item.age_days} days old) - ${item.estimated_monthly_cost}/mo
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>

      {/* AI Chat Panel */}
      {result && (
        <ChatPanel
          demo={isDemo}
          credentialId={!isDemo ? selectedCredId : null}
        />
      )}
    </main>
  );
}
