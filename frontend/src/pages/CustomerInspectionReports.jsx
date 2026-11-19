import React, { useEffect, useState } from 'react';
import { ArrowLeft, ArrowRight, Download } from 'lucide-react';
import { api } from '../services/api';

export default function CustomerInspectionReports({ customer, onBack, onReview }) {
  const [jobs, setJobs] = useState(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let active = true;
    api.getCustomerJobs(customer)
      .then(rows => { if (active) setJobs(rows); })
      .catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [customer, retry]);

  return (
    <section className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
      <header className="flex flex-wrap items-center gap-3 border-b border-gray-200 p-5">
        <button type="button" onClick={onBack} aria-label="Back to recent customers"
          className="rounded border border-gray-200 p-2 text-gray-600 hover:bg-gray-100">
          <ArrowLeft className="h-4 w-4" />
        </button>
        <h1 className="text-lg font-bold text-gray-900">{customer} Inspection Reports</h1>
      </header>

      {error ? (
        <div className="p-5 text-sm">
          <p role="alert" className="text-red-700">{error}</p>
          <button type="button" className="mt-2 font-semibold text-blue-700" onClick={() => {
            setError('');
            setRetry(attempt => attempt + 1);
          }}>Try again</button>
        </div>
      ) : !jobs ? (
        <p role="status" className="p-6 text-center text-sm text-gray-500">Loading inspection reports…</p>
      ) : !jobs.length ? (
        <p className="p-6 text-center text-sm text-gray-500">No inspection reports for this customer.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-gray-200 bg-gray-50 text-xs font-semibold uppercase tracking-wider text-gray-500">
              <tr>
                <th scope="col" className="px-4 py-3">Model &amp; SKU</th>
                <th scope="col" className="px-4 py-3">Job Code</th>
                <th scope="col" className="px-4 py-3">Status</th>
                <th scope="col" className="px-4 py-3">Reports</th>
                <th scope="col" className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {jobs.map(job => (
                <tr key={job.id} className="hover:bg-gray-50">
                  <th scope="row" className="min-w-40 px-4 py-3 text-gray-900">
                    {job.model_name || job.product_type}
                    {job.product_number && <div className="text-xs font-normal text-gray-500">SKU {job.product_number}</div>}
                  </th>
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-gray-700">{job.job_code}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-gray-700">{job.status}</td>
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-gray-600">{job.approved_reports}/{job.total_reports} approved</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <a href={api.getZipDownloadUrl(job.id)} download aria-label={`Download reports for ${job.job_code}`}
                        title="Download all reports" className="rounded p-1.5 text-gray-500 hover:bg-gray-100">
                        <Download className="h-4 w-4" />
                      </a>
                      <button type="button" onClick={() => onReview(job.id)}
                        aria-label={`Review ${job.model_name || job.product_type}, ${job.job_code}`}
                        className="inline-flex items-center gap-1 rounded bg-blue-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-800">
                        Review <ArrowRight className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
