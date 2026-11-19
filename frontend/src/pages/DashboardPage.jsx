import React, { useEffect, useState } from 'react';
import { api } from '../services/api';
import { 
  FileSpreadsheet, 
  CheckCircle, 
  Clock, 
  Mail, 
  ArrowRight,
  Plus, 
  RefreshCw,
} from 'lucide-react';
import CustomerInspectionReports from './CustomerInspectionReports';

export default function DashboardPage({ setActiveTab, setSelectedJobId, customer, setCustomer }) {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadStats = () => {
    setLoading(true);
    api.getDashboardStats()
      .then(setStats)
      .catch((err) => console.error('Error fetching dashboard stats:', err))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (!customer) loadStats();
  }, [customer]);

  if (customer) {
    return (
      <CustomerInspectionReports
        key={customer}
        customer={customer}
        onBack={() => setCustomer('')}
        onReview={(jobId) => {
          setSelectedJobId(jobId);
          setActiveTab('job-review');
        }}
      />
    );
  }

  return (
    <div className="space-y-8">
      {/* Top Banner */}
      <div className="bg-gradient-to-r from-blue-900 via-blue-800 to-indigo-900 rounded-2xl p-6 text-white shadow-lg flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight mt-1">Yathi Pumps PDI Operations Dashboard</h1>
        </div>
        <div className="flex items-center space-x-3">
          <button
            onClick={loadStats}
            className="p-2.5 bg-blue-800/80 hover:bg-blue-700 rounded-lg text-white border border-blue-500/40 transition"
            title="Refresh dashboard"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={() => setActiveTab('new-inspection')}
            className="flex items-center space-x-2 bg-white text-blue-900 font-bold px-4 py-2.5 rounded-lg shadow hover:bg-blue-50 transition"
          >
            <Plus className="w-4 h-4" />
            <span>Generate PDI Reports</span>
          </button>
        </div>
      </div>

      {/* 5 Top Statistics Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        
        <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm">
          <div className="flex items-center justify-between text-gray-500">
            <span className="text-xs font-semibold uppercase tracking-wider">Reports Generated</span>
            <FileSpreadsheet className="w-5 h-5 text-blue-600" />
          </div>
          <div className="mt-2 text-2xl font-bold text-gray-900">{stats?.total_reports_generated ?? 0}</div>
          <p className="text-xs text-gray-400 mt-1">Editable Excel copies</p>
        </div>

        <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm">
          <div className="flex items-center justify-between text-gray-500">
            <span className="text-xs font-semibold uppercase tracking-wider">Completed Jobs</span>
            <CheckCircle className="w-5 h-5 text-green-600" />
          </div>
          <div className="mt-2 text-2xl font-bold text-gray-900">{stats?.completed_jobs ?? 0}</div>
          <p className="text-xs text-gray-400 mt-1">PDI workflow marked complete</p>
        </div>

        <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm">
          <div className="flex items-center justify-between text-gray-500">
            <span className="text-xs font-semibold uppercase tracking-wider">Awaiting Review</span>
            <Clock className="w-5 h-5 text-amber-500" />
          </div>
          <div className="mt-2 text-2xl font-bold text-gray-900">{stats?.awaiting_review ?? 0}</div>
          <p className="text-xs text-gray-400 mt-1">Pending QA sign-off</p>
        </div>

        <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm">
          <div className="flex items-center justify-between text-gray-500">
            <span className="text-xs font-semibold uppercase tracking-wider">Awaiting Email</span>
            <Mail className="w-5 h-5 text-purple-500" />
          </div>
          <div className="mt-2 text-2xl font-bold text-gray-900">{stats?.awaiting_email ?? 0}</div>
          <p className="text-xs text-gray-400 mt-1">Pending customer delivery</p>
        </div>

      </div>

      <section className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="border-b border-gray-200 p-5">
          <h2 className="text-lg font-bold text-gray-900">Recent Inspection Reports</h2>
        </div>
        {loading ? (
          <p className="p-6 text-center text-sm text-gray-500">Loading recent reports...</p>
        ) : stats?.recent_customers?.length ? (
          <ul className="divide-y divide-gray-200">
            {stats.recent_customers.map((name) => (
              <li key={name} className="flex items-center justify-between gap-4 px-5 py-3">
                <span className="text-sm font-semibold text-gray-900">{name}</span>
                <button
                  type="button"
                  onClick={() => setCustomer(name)}
                  aria-label={`Review ${name} inspection reports`}
                  className="inline-flex items-center gap-1 rounded bg-blue-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-800"
                >
                  Review <ArrowRight className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="p-6 text-center text-sm text-gray-500">No recent inspection reports.</p>
        )}
      </section>

    </div>
  );
}
