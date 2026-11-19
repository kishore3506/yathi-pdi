import React, { useEffect, useState } from 'react';
import { api } from '../services/api';

export default function LoginPage({ errorMessage, onLogin }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [setupComplete, setSetupComplete] = useState(null);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.getSetupStatus()
      .then(result => setSetupComplete(result.administrator_configured))
      .catch(() => setSetupComplete(null));
  }, []);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError('');
    try {
      await onLogin(email.trim(), password);
    } catch (loginError) {
      setError(loginError.message || 'Login failed.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-100 px-4 py-10">
      <form onSubmit={handleSubmit} className="w-full max-w-md space-y-5 rounded-2xl border bg-white p-6 shadow-lg sm:p-8">
        <div>
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-700 text-2xl font-black text-white">Y</div>
          <h1 className="mt-4 text-2xl font-bold text-slate-900">Yathi Pumps PDI</h1>
          <p className="mt-1 text-sm text-slate-600">Sign in with your employee account.</p>
        </div>

        {(error || errorMessage) && (
          <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            {error || errorMessage}
          </div>
        )}

        {setupComplete === false && (
          <div role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            <p>Initial administrator setup is required.</p>
            <p className="mt-1">From the project root, run this command in a terminal. No default password is configured.</p>
            <code className="mt-2 block break-all rounded bg-amber-100 px-2 py-1 font-mono text-sm">
              python -m backend.create_admin
            </code>
          </div>
        )}

        <label className="block text-sm font-medium text-slate-700">
          Work email
          <input
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={event => setEmail(event.target.value)}
            className="mt-1.5 min-h-11 w-full rounded-lg border border-slate-300 px-3 py-2 text-base focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-100"
          />
        </label>

        <label className="block text-sm font-medium text-slate-700">
          Password
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={event => setPassword(event.target.value)}
            className="mt-1.5 min-h-11 w-full rounded-lg border border-slate-300 px-3 py-2 text-base focus:border-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-100"
          />
        </label>

        <button
          type="submit"
          disabled={submitting || setupComplete === false}
          className="min-h-11 w-full rounded-lg bg-blue-700 px-4 py-2 font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  );
}
