import React, { useEffect, useState } from 'react';
import { api } from '../services/api';

const EMPTY_USER = { email: '', display_name: '', password: '', role: 'inspector' };

export default function AdminUsersPage({ showAccounts = true }) {
  const [users, setUsers] = useState([]);
  const [form, setForm] = useState(EMPTY_USER);
  const [backupFile, setBackupFile] = useState(null);
  const [backupBusy, setBackupBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  const refreshUsers = async () => setUsers(await api.getUsers());

  useEffect(() => {
    if (showAccounts) refreshUsers().catch(err => setError(err.message));
  }, [showAccounts]);

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await api.createUser(form);
      setForm(EMPTY_USER);
      setNotice('Employee account created.');
      await refreshUsers();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const setActive = async (user) => {
    setError('');
    setNotice('');
    try {
      await api.setUserActive(user.id, !user.is_active);
      setNotice(`Account ${user.is_active ? 'disabled' : 'enabled'}.`);
      await refreshUsers();
    } catch (err) {
      setError(err.message);
    }
  };

  const downloadBackup = async (excel = false) => {
    setBackupBusy(true);
    setError('');
    setNotice('');
    try {
      const { blob, filename } = await (excel ? api.downloadExcelData() : api.downloadBackup());
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = filename;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
      setNotice(excel ? 'Excel data downloaded.' : 'Backup downloaded. Store it in an approved, access-controlled location.');
    } catch (err) {
      setError(err.message);
    } finally {
      setBackupBusy(false);
    }
  };

  const importBackup = async (event) => {
    event.preventDefault();
    if (!backupFile || !window.confirm('Import is permitted only before business data or template changes are added. Continue?')) return;
    setBackupBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await api.importBackup(backupFile);
      setBackupFile(null);
      event.target.reset();
      setNotice(`Backup imported. ${result.imported_files} referenced files restored.`);
      if (showAccounts) await refreshUsers();
    } catch (err) {
      setError(err.message);
    } finally {
      setBackupBusy(false);
    }
  };

  return (
    <section className="mx-auto max-w-4xl space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-slate-900">{showAccounts ? 'Employee accounts' : 'Backups'}</h1>
        {showAccounts && <p className="mt-1 text-sm text-slate-600">Create accounts with the least privilege required. Passwords are stored as Argon2 hashes.</p>}
      </header>

      {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {notice && <p role="status" className="rounded-lg bg-green-50 p-3 text-sm text-green-800">{notice}</p>}

      {showAccounts && <>
      <form onSubmit={submit} className="grid gap-4 rounded-xl border bg-white p-5 sm:grid-cols-2">
        <label className="text-sm font-medium text-slate-700">
          Employee name
          <input required maxLength={120} value={form.display_name} onChange={e => setForm({ ...form, display_name: e.target.value })} className="mt-1 min-h-11 w-full rounded-lg border px-3 py-2 text-base" />
        </label>
        <label className="text-sm font-medium text-slate-700">
          Work email
          <input type="email" required maxLength={254} value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} className="mt-1 min-h-11 w-full rounded-lg border px-3 py-2 text-base" />
        </label>
        <label className="text-sm font-medium text-slate-700">
          Temporary password (12+ characters)
          <input type="password" autoComplete="new-password" minLength={12} required value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} className="mt-1 min-h-11 w-full rounded-lg border px-3 py-2 text-base" />
        </label>
        <label className="text-sm font-medium text-slate-700">
          Role
          <select value={form.role} onChange={e => setForm({ ...form, role: e.target.value })} className="mt-1 min-h-11 w-full rounded-lg border bg-white px-3 py-2 text-base">
            <option value="inspector">Inspector — create and edit inspections</option>
            <option value="approver">Approver — review and approve reports</option>
            <option value="administrator">Administrator — manage access and templates</option>
          </select>
        </label>
        <div className="sm:col-span-2">
          <button type="submit" disabled={busy} className="min-h-11 rounded-lg bg-blue-700 px-5 py-2 font-semibold text-white disabled:opacity-60">
            {busy ? 'Creating…' : 'Create employee'}
          </button>
        </div>
      </form>

      <div className="overflow-x-auto rounded-xl border bg-white">
        <table className="w-full min-w-[560px] text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-600">
            <tr><th className="p-3">Employee</th><th className="p-3">Role</th><th className="p-3">Status</th><th className="p-3">Action</th></tr>
          </thead>
          <tbody>
            {users.map(user => (
              <tr key={user.id} className="border-t">
                <td className="p-3"><span className="block font-medium">{user.display_name}</span><span className="text-xs text-slate-500">{user.email}</span></td>
                <td className="p-3 capitalize">{user.role}</td>
                <td className="p-3">{user.is_active ? 'Active' : 'Disabled'}</td>
                <td className="p-3"><button type="button" onClick={() => setActive(user)} className="min-h-10 rounded-lg border px-3 py-1.5 font-medium">{user.is_active ? 'Disable' : 'Enable'}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      </>}

      <section className="space-y-4 rounded-xl border bg-white p-5">
        <div>
          <h2 className="text-lg font-bold text-slate-900">Business data backup</h2>
          <p className="mt-1 text-sm text-slate-600">The Excel copy updates automatically as records change. The full ZIP backup includes the SQLite database and the original uploaded documents and report files.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => downloadBackup(true)} disabled={backupBusy} className="min-h-11 rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">
            Download Excel data
          </button>
          <button type="button" onClick={() => downloadBackup()} disabled={backupBusy} className="min-h-11 rounded-lg border px-4 py-2 text-sm font-semibold disabled:opacity-60">
            Download full ZIP backup
          </button>
        </div>
        <form onSubmit={importBackup} className="space-y-3 border-t pt-4">
          <label className="block text-sm font-medium text-slate-700">
            One-time import of a backup created by this application
            <input type="file" accept=".zip,application/zip" required onChange={event => setBackupFile(event.target.files?.[0] || null)} className="mt-2 block w-full text-sm" />
          </label>
          <button type="submit" disabled={!backupFile || backupBusy} className="min-h-11 rounded-lg bg-amber-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60">
            Import into an empty app
          </button>
          <p className="text-xs text-amber-900">
            Import is permitted only before business records or template changes exist.
            {showAccounts && ' Current accounts are preserved and backup accounts are added by email.'}
            {' Files are restored under new names.'}
          </p>
        </form>
      </section>
    </section>
  );
}
