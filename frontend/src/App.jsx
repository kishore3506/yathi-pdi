import React, { useEffect, useState } from 'react';
import Navbar from './components/Navbar';
import LoginPage from './components/LoginPage';
import UpdateControls from './components/UpdateControls';
import DashboardPage from './pages/DashboardPage';
import NewInspectionPage from './pages/NewInspectionPage';
import GeneratedReportsPage from './pages/GeneratedReportsPage';
import ReportEditorPage from './pages/ReportEditorPage';
import TemplateManagementPage from './pages/TemplateManagementPage';
import AdminUsersPage from './pages/AdminUsersPage';
import ChatAssistant from './components/ChatAssistant';
import { api } from './services/api';

export default function App() {
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState('');
  const [version, setVersion] = useState(null);
  const [activeTab, setActiveTab] = useState('dashboard');
  const [selectedJobId, setSelectedJobId] = useState(null);
  const [dashboardCustomer, setDashboardCustomer] = useState('');
  const [selectedReportId, setSelectedReportId] = useState(null);
  const [generatedJobs, setGeneratedJobs] = useState([]);
  const [selectedReviewJobId, setSelectedReviewJobId] = useState('');
  const [generationWarning, setGenerationWarning] = useState('');

  useEffect(() => {
    let active = true;
    api.getCurrentUser()
      .then(currentUser => {
        if (active) setUser(currentUser);
      })
      .catch(error => {
        if (!active) return;
        if (error.message !== 'Login required.') setAuthError(error.message);
      })
      .finally(() => {
        if (active) setAuthLoading(false);
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!user) return;
    api.getVersion().then(setVersion).catch(() => setVersion(null));
  }, [user]);

  const handleLogin = async (email, password) => {
    const signedInUser = await api.login(email, password);
    setUser(signedInUser);
    setAuthError('');
  };

  const handleLogout = async () => {
    try {
      await api.logout();
      setUser(null);
      setActiveTab('dashboard');
      setSelectedJobId(null);
      setDashboardCustomer('');
      setSelectedReportId(null);
    } catch (error) {
      setAuthError(error.message);
    }
  };

  if (authLoading) {
    return <main className="flex min-h-screen items-center justify-center text-sm text-slate-600">Connecting to the PDI service…</main>;
  }

  if (!user) {
    if (authError) {
      return (
        <main className="flex min-h-screen flex-col items-center justify-center gap-4 px-4 text-center text-sm text-slate-700">
          <p role="alert">{authError}</p>
          <button type="button" onClick={() => window.location.reload()}
            className="rounded-md bg-blue-700 px-4 py-2 font-semibold text-white">
            Try again
          </button>
        </main>
      );
    }
    return (
      <>
        <UpdateControls />
        <LoginPage errorMessage={authError} onLogin={handleLogin} />
      </>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 font-sans text-slate-900">
      <UpdateControls />
      <Navbar activeTab={activeTab} setActiveTab={(tab) => {
        setDashboardCustomer('');
        setActiveTab(tab);
      }} user={user} onLogout={handleLogout} />
      {authError && (
        <p role="alert" className="mx-auto mt-3 max-w-3xl rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800">
          {authError}
        </p>
      )}

      <div className="mb-16 flex min-h-screen min-w-0 flex-col md:mb-0 md:ml-60">
        <main className="mx-auto w-full max-w-7xl flex-1 px-3 py-6 sm:px-6 sm:py-8 lg:px-8">
          {activeTab === 'dashboard' && (
            <DashboardPage
              setActiveTab={setActiveTab}
              setSelectedJobId={setSelectedJobId}
              customer={dashboardCustomer}
              setCustomer={setDashboardCustomer}
            />
          )}

          {activeTab === 'new-inspection' && (
            <NewInspectionPage
              setActiveTab={setActiveTab}
              generatedJobs={generatedJobs}
              setGeneratedJobs={setGeneratedJobs}
              setSelectedReviewJobId={setSelectedReviewJobId}
              setGenerationWarning={setGenerationWarning}
            />
          )}

          {activeTab === 'generated-reports' && (
            <GeneratedReportsPage
              generatedJobs={generatedJobs}
              selectedReviewJobId={selectedReviewJobId}
              setSelectedReviewJobId={setSelectedReviewJobId}
              generationWarning={generationWarning}
              setActiveTab={setActiveTab}
              setSelectedJobId={setSelectedJobId}
            />
          )}

          {activeTab === 'job-review' && (
            <ReportEditorPage
              jobId={selectedJobId}
              backLabel={dashboardCustomer ? `Back to ${dashboardCustomer} inspection reports` : undefined}
              setActiveTab={setActiveTab}
              setSelectedJobId={setSelectedJobId}
            />
          )}

          {activeTab === 'report-editor' && (
            <ReportEditorPage
              reportId={selectedReportId}
              setActiveTab={setActiveTab}
              setSelectedJobId={setSelectedJobId}
            />
          )}

          {activeTab === 'templates' && (
            <TemplateManagementPage />
          )}
          {activeTab === 'employees' && user.role === 'administrator' && !user.local_access && (
            <AdminUsersPage />
          )}
          {activeTab === 'backups' && user.local_access && (
            <AdminUsersPage showAccounts={false} />
          )}
        </main>
        <footer className="px-4 pb-3 text-center text-xs text-slate-500">
          {version ? `Version ${version.version} · ${version.commit}` : 'Version unavailable'}
          <span className="ml-2">Report generation and document extraction require a connection.</span>
        </footer>
      </div>

      <ChatAssistant screen={activeTab} jobId={selectedJobId} reportId={selectedReportId} />
    </div>
  );
}
