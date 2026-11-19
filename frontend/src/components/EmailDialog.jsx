import React, { useEffect, useState } from 'react';
import { api } from '../services/api';
import { Mail, CheckCircle2, AlertTriangle, Loader2, X, Paperclip, Send } from 'lucide-react';

export default function EmailDialog({
  isOpen,
  onClose,
  job,
  onEmailSuccess,
  onReviewPdiReports,
  onReviewLegal,
}) {
  const [fromEmail, setFromEmail] = useState('');
  const [toEmail, setToEmail] = useState(job?.customer_email || '');
  const [customerName, setCustomerName] = useState(job?.customer_name || '');
  const [subject, setSubject] = useState('');
  const [message, setMessage] = useState('');
  const [emailConfigured, setEmailConfigured] = useState(false);
  const [emailProvider, setEmailProvider] = useState('n8n');
  const [sending, setSending] = useState(false);
  const [skipping, setSkipping] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const emailModelJobs = job?.model_jobs?.length ? job.model_jobs : (job ? [job] : []);
  const isHavellsJob = String(job?.company_name || '').trim().toLowerCase() === 'havells';
  const hasApprovalGate = isHavellsJob || emailModelJobs.length > 1;
  const pendingPdiJob = hasApprovalGate && emailModelJobs.find(modelJob => {
    const currentReports = Number(modelJob.id) === Number(job.id) ? (job.reports || []) : [];
    const approvedCount = currentReports.length
      ? currentReports.filter(report => ['Approved', 'Emailed'].includes(report.status)).length
      : Number(modelJob.approved_reports || 0);
    const totalReports = Number(modelJob.total_reports || currentReports.length || 0);
    return approvedCount < totalReports;
  });
  const pendingLegalJob = isHavellsJob
    ? emailModelJobs.find(modelJob => modelJob.legal_status !== 'Agreed')
    : null;
  const hasPendingPdiReports = Boolean(pendingPdiJob);
  const legalChecklistPending = !hasPendingPdiReports && Boolean(pendingLegalJob);
  const workflowBlockMessage = hasPendingPdiReports
    ? 'Approve every PDI report for every model before emailing the inspection batch.'
    : legalChecklistPending
      ? 'Agree to the J1 legal checklist for every model before emailing the inspection batch.'
      : '';
  const reportCount = emailModelJobs.reduce(
    (total, modelJob) => total + Number(modelJob.total_reports || modelJob.reports?.length || 0),
    0
  ) || job?.reports?.length || job?.total_reports || 1;

  useEffect(() => {
    if (!isOpen || !job) return;
    let active = true;
    const name = job.customer_name || 'Customer';
    const modelJobs = job.model_jobs?.length ? job.model_jobs : [job];
    const modelSummary = modelJobs.map(modelJob => (
      `- ${modelJob.model_name || modelJob.product_type || 'Model'} ` +
      `(SKU ${modelJob.product_number || '-'}, PO ${modelJob.po_number || '-'}, Lot ${modelJob.lot_size || '-'})`
    )).join('\n');
    setEmailConfigured(false);
    setFromEmail('');
    setToEmail(job.customer_email || '');
    setCustomerName(job.customer_name || '');
    setSubject(
      modelJobs.length > 1
        ? `PDI Reports - ${modelJobs.length} Models - ${job.job_code}`
        : `PDI Reports - Job ${job.job_code}`
    );
    setMessage(
      `Dear ${name},\n\nPlease find attached the approved PDI reports${isHavellsJob ? ' and agreed J1 legal compliance checklists' : ''} ` +
      `for ${modelJobs.length > 1 ? 'all models in this inspection' : `job ${job.job_code}`}.\n\n` +
      `Models included:\n${modelSummary}\n\nBest regards,\nYathi Pumps QA Team`
    );
    setResult(null);
    setError('');
    api.getEmailConfig()
      .then((config) => {
        if (!active) return;
        setFromEmail(config.from_email || '');
        setEmailConfigured(config.configured);
        setEmailProvider(config.provider || 'n8n');
        if (!config.configured) {
          setError(config.provider === 'n8n'
            ? 'Configure the company n8n webhook and sender in the hosting environment.'
            : 'Configure the company Gmail SMTP account in the hosting environment.');
        }
      })
      .catch((err) => {
        if (!active) return;
        setEmailConfigured(false);
        setError(err.message || 'Could not load email settings.');
      });
    return () => {
      active = false;
    };
  }, [isOpen, job]);

  if (!isOpen || !job) return null;

  const handleSendEmail = async () => {
    if (workflowBlockMessage) return;
    if (!emailConfigured) {
      setError(emailProvider === 'n8n'
        ? 'Configure the company n8n webhook and sender in the hosting environment.'
        : 'Configure the company Gmail SMTP account in the hosting environment.');
      return;
    }
    if (!fromEmail.trim() || !toEmail.trim() || !subject.trim() || !message.trim()) {
      setError('Please complete the From, To, Subject, and Message fields.');
      return;
    }
    const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailPattern.test(fromEmail.trim()) || !emailPattern.test(toEmail.trim())) {
      setError('Please enter valid From and To email addresses.');
      return;
    }
    setSending(true);
    setError('');
    try {
      const res = await api.sendEmail({
        job_id: job.id,
        from_email: fromEmail.trim(),
        to_email: toEmail.trim(),
        customer_email: toEmail.trim(),
        customer_name: customerName,
        subject: subject.trim(),
        message: message.trim(),
        skip: false
      });
      if (!res.success) throw new Error(res.message || res.response || 'Email delivery failed');
      setResult(res);
      if (onEmailSuccess) onEmailSuccess(res);
    } catch (err) {
      setError(err.message || 'Email delivery failed');
    } finally {
      setSending(false);
    }
  };

  const handleSkip = async () => {
    setSkipping(true);
    setError('');
    try {
      const res = await api.sendEmail({
        job_id: job.id,
        skip: true
      });
      setResult(res);
      if (onEmailSuccess) onEmailSuccess(res);
    } catch (err) {
      setError(err.message || 'Failed to update job status');
    } finally {
      setSkipping(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/50 p-3">
      <div className="relative flex max-h-[calc(100dvh-1.5rem)] w-full max-w-md flex-col overflow-hidden rounded-xl border bg-white p-4 shadow-2xl">
        
        <button
          onClick={onClose}
          className="absolute right-3 top-3 text-gray-400 hover:text-gray-600"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="mb-3 flex shrink-0 items-center space-x-2.5 border-b pb-2.5 pr-7 text-gray-900">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-red-100 text-red-700">
            <Mail className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-base font-bold">Send PDI Reports to Customer</h3>
            <p className="text-xs text-gray-500">Send through the configured company email service ({emailProvider})</p>
          </div>
        </div>

        {error && (
          <div className="mb-3 flex shrink-0 items-center space-x-2 rounded-lg bg-red-50 p-2.5 text-xs text-red-700">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {workflowBlockMessage && (
          <div role="alert" className="mb-3 shrink-0 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
            <p>{workflowBlockMessage}</p>
            <button
              type="button"
              onClick={() => {
                if (hasPendingPdiReports) {
                  onReviewPdiReports?.(pendingPdiJob.id);
                } else {
                  onReviewLegal?.(pendingLegalJob.id);
                }
              }}
              className="mt-2 font-bold underline"
            >
              {hasPendingPdiReports ? 'Review pending model' : 'Review pending J1 checklist'}
            </button>
          </div>
        )}

        {result ? (
          <div className="space-y-3 overflow-y-auto">
            <div className={`space-y-1 rounded-lg border p-3 text-sm ${
              result.status === 'Sent'
                ? 'bg-green-50 text-green-800 border-green-200'
                : result.status === 'Skipped'
                  ? 'bg-amber-50 text-amber-800 border-amber-200'
                  : 'bg-red-50 text-red-800 border-red-200'
            }`}>
              <div className="flex items-center space-x-2 font-bold">
                <CheckCircle2 className="w-5 h-5 text-green-600" />
                <span>
                  {result.status === 'Sent'
                    ? result.model_count > 1
                      ? `Reports for all ${result.model_count} models sent successfully!`
                      : 'Reports sent successfully!'
                    : result.status === 'Skipped'
                      ? 'Email step skipped.'
                      : 'Email delivery failed.'}
                </span>
              </div>
              <p className="text-xs">
                {result.status === 'Sent'
                  ? `From ${result.from_email || fromEmail} to ${result.customer_email}.`
                  : result.message || 'Job state updated. You can dispatch later from the dashboard.'}
              </p>
            </div>

            <div className="flex justify-end">
              <button
                onClick={onClose}
                className="rounded-lg bg-gray-900 px-5 py-2 text-sm font-semibold text-white hover:bg-black"
              >
                Done
              </button>
            </div>
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="min-h-0 flex-1 overflow-y-auto pr-1">
              <div className="space-y-2.5">
                <p className="text-sm font-medium text-gray-700">
                  Would you like to send the official approved PDI reports to the customer now?
                </p>

                <div className="space-y-2.5 rounded-lg border bg-gray-50 p-3">
                  <div>
                    <label className="mb-1 block text-xs font-semibold uppercase text-gray-600">
                      Customer / Recipient Name
                    </label>
                    <input
                      type="text"
                      value={customerName}
                      onChange={(e) => setCustomerName(e.target.value)}
                      placeholder="Customer Contact / Company"
                      className="w-full rounded-lg border bg-white px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-red-500"
                    />
                  </div>

                  <div>
                    <label className="mb-1 block text-xs font-semibold uppercase text-gray-600">
                      From Email *
                    </label>
                    <input
                      type="email"
                      required
                      value={fromEmail}
                      onChange={(e) => setFromEmail(e.target.value)}
                      placeholder="sender@company.com"
                      className="w-full rounded-lg border bg-white px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-red-500"
                    />
                    <p className="mt-1 text-[11px] text-gray-500">
                      Use the configured company sender address or a verified alias.
                    </p>
                  </div>

                  <div>
                    <label className="mb-1 block text-xs font-semibold uppercase text-gray-600">
                      To Email *
                    </label>
                    <input
                      type="email"
                      required
                      value={toEmail}
                      onChange={(e) => setToEmail(e.target.value)}
                      placeholder="customer@domain.com"
                      className="w-full rounded-lg border bg-white px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-red-500"
                    />
                  </div>

                  <div>
                    <label className="mb-1 block text-xs font-semibold uppercase text-gray-600">
                      Subject *
                    </label>
                    <input
                      type="text"
                      required
                      value={subject}
                      onChange={(e) => setSubject(e.target.value)}
                      className="w-full rounded-lg border bg-white px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-red-500"
                    />
                  </div>

                  <div>
                    <label className="mb-1 block text-xs font-semibold uppercase text-gray-600">
                      Message *
                    </label>
                    <textarea
                      required
                      rows={3}
                      value={message}
                      onChange={(e) => setMessage(e.target.value)}
                      placeholder="Write the email contents..."
                      className="min-h-20 w-full resize-y rounded-lg border bg-white p-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500"
                    />
                  </div>

                  <div className="flex items-center justify-between border-t pt-2 text-xs text-gray-600">
                    <span className="flex items-center space-x-1">
                      <Paperclip className="h-4 w-4 text-gray-400" />
                      <span>
                        Attachments: <b>{reportCount} PDI Report(s){isHavellsJob ? ` + ${emailModelJobs.length} J1 legal PDF(s)` : ''}</b>
                      </span>
                    </span>
                    <span className="font-mono text-gray-500">{job.job_code}</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="flex shrink-0 items-center justify-between border-t bg-white pt-3">
              <button
                type="button"
                onClick={handleSkip}
                disabled={sending || skipping}
                className="rounded-lg px-3 py-2 text-sm font-semibold text-gray-500 hover:bg-gray-100 hover:text-gray-700"
              >
                {skipping ? 'Skipping...' : 'Skip for Now'}
              </button>

              <button
                type="button"
                onClick={handleSendEmail}
                disabled={sending || skipping || Boolean(workflowBlockMessage)}
                className="flex items-center space-x-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-bold text-white shadow hover:bg-red-700"
              >
                {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                <span>{sending ? 'Sending Email...' : 'Send Email'}</span>
              </button>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
