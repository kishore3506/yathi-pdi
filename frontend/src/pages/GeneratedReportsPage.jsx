import React from 'react';
import { ArrowLeft, ArrowRight, Download, Plus } from 'lucide-react';
import { api } from '../services/api';

export default function GeneratedReportsPage({
  generatedJobs,
  selectedReviewJobId,
  setSelectedReviewJobId,
  generationWarning,
  setActiveTab,
  setSelectedJobId
}) {
  const selectedJob = generatedJobs.find(
    job => String(job.job_id) === selectedReviewJobId
  );

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <button
        type="button"
        onClick={() => setActiveTab('dashboard')}
        className="inline-flex items-center gap-2 text-sm font-semibold text-gray-600 hover:text-gray-900"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Dashboard
      </button>

      <div>
        <h1 className="text-2xl font-bold tracking-tight text-gray-900">Generated reports by model</h1>
        <p className="mt-1 text-sm text-gray-500">Select a model card to review its reports.</p>
      </div>

      {generationWarning && (
        <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          {generationWarning}
        </div>
      )}

      {generatedJobs.length > 0 ? (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 2xl:grid-cols-3">
            {generatedJobs.map(job => (
              <button
                key={job.job_id}
                type="button"
                aria-pressed={String(job.job_id) === selectedReviewJobId}
                onClick={() => setSelectedReviewJobId(String(job.job_id))}
                className={`w-full space-y-4 rounded-xl border p-4 text-left shadow-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
                  String(job.job_id) === selectedReviewJobId
                    ? 'border-blue-500 bg-blue-50 ring-2 ring-blue-200'
                    : 'border-blue-100 bg-white hover:border-blue-300'
                }`}
              >
                <div className="min-w-0">
                  <h2 className="break-words font-bold text-gray-900">{job.model_name || job.product_number}</h2>
                  <p className="mt-1 text-xs text-gray-600">SKU {job.product_number} · PO {job.po_number}</p>
                  {job.legal_status && (
                    <p className="mt-2 text-xs font-medium text-indigo-700">
                      J1 legal checksheet generated for review after the PDI reports.
                    </p>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  {(job.reports || []).map(report => (
                    <div key={report.id} className="min-w-[145px] flex-1 rounded-lg border bg-gray-50 p-3 text-sm">
                      <div className="break-all font-mono font-semibold text-gray-800">{report.report_code}</div>
                    </div>
                  ))}
                </div>
              </button>
            ))}
          </div>

          <div className="flex flex-wrap justify-end gap-3 border-t border-gray-200 pt-4">
            {selectedJob?.reports?.filter(report => (
              report.report_data?.format === 'docx' || report.report_data?.primary_sheet === 'KSB PDI FORMAT'
              || report.report_data?.primary_sheet === 'Crompton MBD R4'
              || selectedJob.company_name?.trim().toLowerCase() === 'havells'
            )).map(report => (
              <a key={report.id} href={report.report_data?.primary_sheet === 'Crompton MBD R4'
                ? api.getPdfDownloadUrl(report.id) : api.getDocumentDownloadUrl(report.id)}
                className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-white px-4 py-2.5 text-sm font-semibold text-blue-800">
                <Download className="h-4 w-4" />
                {report.report_data?.format === 'docx' ? 'Download Word report'
                  : report.report_data?.primary_sheet === 'Crompton MBD R4' ? 'Download PDF report' : `Download Excel report ${report.unit_index}`}
              </a>
            ))}
            <button
              type="button"
              disabled={!selectedJob}
              onClick={() => {
                if (!selectedJob) return;
                setSelectedJobId(selectedJob.job_id);
                setActiveTab('job-review');
              }}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:bg-gray-300"
            >
              Review this model&apos;s reports
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </>
      ) : (
        <div className="rounded-xl border border-gray-200 bg-white p-8 text-center shadow-sm">
          <p className="text-sm text-gray-600">No generated reports to display.</p>
          <button
            type="button"
            onClick={() => setActiveTab('new-inspection')}
            className="mt-4 inline-flex items-center gap-2 rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-800"
          >
            <Plus className="h-4 w-4" />
            New Inspection
          </button>
        </div>
      )}
    </div>
  );
}
