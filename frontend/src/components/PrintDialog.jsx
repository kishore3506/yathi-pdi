import React, { useEffect, useState } from 'react';
import { api } from '../services/api';
import { Printer, AlertTriangle, Loader2, X, ExternalLink } from 'lucide-react';

export default function PrintDialog({ isOpen, onClose, jobId, reportId }) {
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    let active = true;
    setError('');
    if (reportId) {
      setReports([{ id: reportId, report_code: `Report ${reportId}` }]);
      return () => { active = false; };
    }
    if (!jobId) {
      setReports([]);
      return () => { active = false; };
    }
    setLoading(true);
    api.getJobDetails(jobId)
      .then(job => {
        if (active) setReports(job.reports || []);
      })
      .catch(err => {
        if (active) setError(err.message || 'Could not load reports.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [isOpen, jobId, reportId]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/50 p-4">
      <section role="dialog" aria-modal="true" aria-labelledby="device-print-title" className="relative max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-xl border bg-white p-5 shadow-2xl sm:p-6">
        <button type="button" onClick={onClose} aria-label="Close" className="absolute right-4 top-4 rounded-lg p-2 text-gray-500 hover:bg-gray-100">
          <X className="h-5 w-5" />
        </button>
        <div className="flex items-center gap-3 border-b pb-3 pr-8">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-100 text-indigo-700"><Printer className="h-5 w-5" /></div>
          <div>
            <h2 id="device-print-title" className="text-lg font-bold text-gray-900">Print from this device</h2>
            <p className="text-xs text-gray-500">The cloud service cannot access office printers.</p>
          </div>
        </div>

        <p className="my-4 rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm text-blue-900">
          Open a PDF, then use the PDF viewer or your browser’s print command. A PDF being opened or downloaded is not recorded as a completed physical print.
        </p>

        {error && <div role="alert" className="mb-4 flex gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-800"><AlertTriangle className="h-4 w-4 shrink-0" />{error}</div>}
        {loading ? (
          <p className="flex items-center gap-2 py-4 text-sm text-gray-600"><Loader2 className="h-4 w-4 animate-spin" />Loading reports…</p>
        ) : (
          <ul className="space-y-2">
            {reports.map(report => (
              <li key={report.id} className="flex items-center justify-between gap-3 rounded-lg border p-3">
                <span className="min-w-0 truncate text-sm font-medium">{report.report_code || `Report ${report.id}`}</span>
                <a
                  href={api.getPdfOpenUrl(report.id)}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex min-h-10 shrink-0 items-center gap-2 rounded-lg bg-indigo-700 px-3 py-2 text-sm font-semibold text-white"
                >
                  Open PDF <ExternalLink className="h-4 w-4" />
                </a>
              </li>
            ))}
            {!reports.length && !error && !loading && <li className="py-4 text-sm text-gray-500">No reports are available for this inspection.</li>}
          </ul>
        )}

        <div className="mt-5 flex justify-end">
          <button type="button" onClick={onClose} className="min-h-10 rounded-lg border px-4 py-2 text-sm font-medium">Close</button>
        </div>
      </section>
    </div>
  );
}
