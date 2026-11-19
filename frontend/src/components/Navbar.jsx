import React, { useEffect, useState } from 'react';
import { api, getConnectionMessage } from '../services/api';
import { LayoutDashboard, PlusCircle, Layers, Cpu, Users, LogOut, Archive } from 'lucide-react';

export default function Navbar({ activeTab, setActiveTab, user, onLogout }) {
  const [health, setHealth] = useState(null);
  const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    ...(['inspector', 'administrator'].includes(user?.role)
      ? [{ id: 'new-inspection', label: 'New Inspection', icon: PlusCircle }]
      : []),
    ...(user?.role === 'administrator' ? [
      { id: 'templates', label: 'Templates', icon: Layers },
      user.local_access
        ? { id: 'backups', label: 'Backups', icon: Archive }
        : { id: 'employees', label: 'Employees', icon: Users },
    ] : []),
  ];

  useEffect(() => {
    let active = true;
    let timeoutId;
    const checkHealth = async () => {
      try {
        const result = await api.checkHealth();
        if (!active) return;

        setHealth(result);
        const isConnected = result?.gemini?.status === 'connected';
        timeoutId = window.setTimeout(checkHealth, isConnected ? 60_000 : 10_000);
      } catch {
        if (!active) return;

        setHealth({ status: 'offline' });
        timeoutId = window.setTimeout(checkHealth, 10_000);
      }
    };

    void checkHealth();
    return () => {
      active = false;
      window.clearTimeout(timeoutId);
    };
  }, []);

  const renderLinks = (mobile = false) => navItems.map(({ id, label, icon: Icon }) => (
    <button
      key={id}
      type="button"
      onClick={() => setActiveTab(id)}
      aria-current={activeTab === id ? 'page' : undefined}
      title={label}
      className={`flex ${mobile ? 'min-w-0 flex-1 flex-col gap-1 py-2 text-[10px]' : 'w-full justify-center gap-3 px-3 py-2.5 text-sm md:justify-start'} items-center rounded-md transition-colors ${
        activeTab === id
          ? 'bg-blue-50 font-semibold text-blue-700'
          : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
      }`}
    >
      <Icon className="h-5 w-5 shrink-0" />
      <span className={mobile ? 'truncate' : 'hidden md:inline'}>{label}</span>
    </button>
  ));

  return (
    <>
    {health?.status === 'offline' && (
      <div role="alert" className="fixed inset-x-0 top-0 z-[60] bg-amber-100 px-4 py-2 text-center text-sm font-medium text-amber-950">
        {getConnectionMessage()}
      </div>
    )}
    <aside className="fixed inset-y-0 left-0 z-50 hidden w-60 flex-col border-r border-gray-200 bg-white shadow-sm md:flex">
      <div className="px-2 pt-4 md:px-4">
        <button
          type="button"
          className="flex w-full items-center justify-center gap-3 rounded-lg p-1 text-left md:justify-start"
          onClick={() => setActiveTab('dashboard')}
          aria-label="Yathi Pumps dashboard"
          title="Yathi Pumps PDI Automation"
        >
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-blue-700 text-xl font-black tracking-wider text-white shadow-md">
            Y
          </span>
          <span className="hidden min-w-0 md:block">
            <span className="block whitespace-nowrap text-sm font-extrabold tracking-tight text-gray-900">YATHI PUMPS</span>
            <span className="mt-1 inline-block rounded bg-blue-100 px-2 py-0.5 text-[10px] font-bold text-blue-800">PDI AUTOMATION</span>
          </span>
        </button>
      </div>

      <nav className="mt-6 flex flex-col gap-2 px-2 md:px-4" aria-label="Main navigation">
        {renderLinks()}
      </nav>

      <div className="mt-auto border-t border-gray-200 p-2 md:p-4">
        <div
          className="flex items-center justify-center gap-2 rounded-lg bg-gray-50 px-2 py-2 text-xs md:justify-start md:px-3"
          title={`Gemini AI: ${health?.gemini?.active_model || health?.gemini?.status || 'Checking'}`}
        >
          <Cpu className="h-4 w-4 shrink-0 text-gray-500" />
          <span className="hidden text-gray-600 md:inline">Gemini AI:</span>
          {health?.gemini?.status === 'connected' ? (
            <span className="hidden min-w-0 break-all font-semibold text-green-700 md:inline">
              {health.gemini.active_model}
            </span>
          ) : (
            <span className="hidden text-amber-600 md:inline">
              {health?.gemini?.status === 'not_configured'
                ? 'API key needed'
                : health?.gemini?.status === 'checking'
                  ? 'Checking'
                  : 'Unavailable'}
            </span>
          )}
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${
              health?.gemini?.status === 'connected' ? 'bg-green-500' : 'bg-amber-400'
            }`}
          />
        </div>
        {!user?.local_access && <div className="mt-3 flex items-center justify-between gap-2">
          <div className="min-w-0">
            <span className="block truncate text-xs font-semibold text-gray-800">{user?.display_name}</span>
            <span className="block text-[10px] capitalize text-gray-500">{user?.role}</span>
          </div>
          <button type="button" onClick={onLogout} aria-label="Sign out" title="Sign out" className="min-h-10 rounded-lg p-2 text-gray-600 hover:bg-gray-100">
            <LogOut className="h-4 w-4" />
          </button>
        </div>}
      </div>
    </aside>
    <nav className="fixed inset-x-0 bottom-0 z-50 flex items-stretch border-t border-gray-200 bg-white px-1 pb-[env(safe-area-inset-bottom)] shadow-lg md:hidden" aria-label="Main navigation">
      {renderLinks(true)}
      {!user?.local_access && <button type="button" onClick={onLogout} aria-label="Sign out" className="flex min-w-14 flex-col items-center justify-center gap-1 py-2 text-[10px] text-gray-600">
        <LogOut className="h-5 w-5" />
        <span>Sign out</span>
      </button>}
    </nav>
    </>
  );
}
