import React, { useState, useEffect } from 'react';
import { api } from '../services/api';
import PrintDialog from '../components/PrintDialog';
import EmailDialog from '../components/EmailDialog';
import LegalChecklistReview from './LegalChecklistReview';
import StgPhotoSlots from '../components/StgPhotoSlots';
import KsbObservations from '../components/KsbObservations';
import sterlingLogo from '../assets/sterling-sites.png';
import { publishUnsavedChanges } from '../services/dirtyState';
import { 
  Download, 
  Printer, 
  Mail, 
  ArrowLeft, 
  ShieldCheck, 
  AlertCircle,
  ExternalLink,
  Loader2,
  RefreshCw
} from 'lucide-react';

const SUPPLIER_NAME = 'Yathi Pumps';
const SUPPLIER_LOCATION = 'Coimbatore';
const CROMPTON_SHEET = 'Crompton MBD R4';
const CROMPTON_FIELDS = [
  ['supplier_name', 'Name of the Unit'],
  ['supplier_location', 'Address of the Unit'],
  ['inspection_date', 'Date of Inspection'],
  ['tds_reference', 'TDS/TI Reference'],
  ['product_reference', 'Product Reference'],
  ['batch_code', 'Batch Code / CCI Reference'],
  ['vendor_report_number', 'Vendor PDI Report Number'],
  ['additional_info', 'Additional Information'],
  ['deviation_number', 'Deviation Note Number'],
  ['deviation_authority', 'Deviation Approval Authority'],
];
const CROMPTON_DECISIONS = ['Direct Pass', 'Rejected', 'Passed after Rework', 'Passed under deviation without rework'];
export default function ReportEditorPage({ jobId, reportId, setActiveTab, setSelectedJobId, backLabel = 'Back to Dashboard' }) {
  const [job, setJob] = useState(null);
  const [currentReport, setCurrentReport] = useState(null);
  const [activeUnitIndex, setActiveUnitIndex] = useState(1);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);
  const [approving, setApproving] = useState(false);
  const [stgSaving, setStgSaving] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [showLegalReview, setShowLegalReview] = useState(false);
  const [legalChecklist, setLegalChecklist] = useState(null);

  // Dialog states
  const [isPrintOpen, setIsPrintOpen] = useState(false);
  const [isEmailOpen, setIsEmailOpen] = useState(false);

  // Editable fields in current report
  const [editHeader, setEditHeader] = useState({});
  const [editObservations, setEditObservations] = useState({});
  const [finalJudgment, setFinalJudgment] = useState('OK');
  const [rejectReason, setRejectReason] = useState('');

  // Load job and report details
  const loadJobData = async () => {
    setLoading(true);
    setErrorMsg('');
    try {
      if (jobId) {
        const j = await api.getJobDetails(jobId);
        setJob(j);
        setLegalChecklist(j.legal_checklist || null);
        setShowLegalReview(
          String(j.company_name).trim().toLowerCase() === 'havells' &&
          j.legal_status !== 'Agreed' &&
          j.reports?.length > 0 &&
          j.reports.every(report => ['Approved', 'Emailed'].includes(report.status))
        );
        if (j.reports && j.reports.length > 0) {
          const rep = j.reports.find(r => r.unit_index === activeUnitIndex) || j.reports[0];
          initReportForm(rep);
        }
        return j;
      } else if (reportId) {
        const rep = await api.getReport(reportId);
        initReportForm(rep);
        if (rep.job_id) {
          const j = await api.getJobDetails(rep.job_id);
          setJob(j);
          setLegalChecklist(j.legal_checklist || null);
          setShowLegalReview(
            String(j.company_name).trim().toLowerCase() === 'havells' &&
            j.legal_status !== 'Agreed' &&
            j.reports?.length > 0 &&
            j.reports.every(report => ['Approved', 'Emailed'].includes(report.status))
          );
          return j;
        }
      }
    } catch (err) {
      setErrorMsg(err.message || 'Failed to load report details');
    } finally {
      setLoading(false);
    }
    return null;
  };

  const initReportForm = (rep) => {
    setCurrentReport(rep);
    setActiveUnitIndex(rep.unit_index || 1);
    const rData = rep.report_data || {};
    const hdr = rData.header_data || {};
    if (rData.format === 'docx') {
      setEditHeader(hdr);
      setEditObservations({});
      return;
    }
    const isFalcon = rData.primary_sheet === 'Falcon PDI';
    const isKsb = rData.primary_sheet === 'KSB PDI FORMAT';
    const isCrompton = rData.primary_sheet === CROMPTON_SHEET;
    const headerData = {
      supplier_name: SUPPLIER_NAME,
      supplier_location: SUPPLIER_LOCATION,
      sku_no: hdr.sku_no || '',
      model_name: hdr.model_name || '',
      po_number: hdr.po_number || '',
      lot_qty: hdr.lot_qty || '',
      po_total_qty: hdr.po_total_qty || '',
      inspected_by: hdr.inspected_by || (isFalcon || isKsb || isCrompton ? '' : 'Yathi QA Inspector'),
      approved_by: hdr.approved_by || (isFalcon || isKsb || isCrompton ? '' : 'Quality Head'),
      inspection_date: hdr.inspection_date || '',
      lot_dispatch_date: hdr.lot_dispatch_date || '',
    };
    if (isKsb) headerData.special_remarks = hdr.special_remarks || '';
    if (isCrompton) {
      for (const [key] of CROMPTON_FIELDS) headerData[key] = hdr[key] || '';
      headerData.note = hdr.note || '';
    }
    if (isFalcon) {
      for (const field of ['power_rating', 'incoming_date', 'invoice_number', 'prepared_by']) {
        headerData[field] = hdr[field] || '';
      }
    }
    const isRejectSelected = String(hdr.judgment_reject || '').includes('✔');
    const nextJudgment = isCrompton ? hdr.final_judgment || ''
      : isRejectSelected ? 'Reject' : isKsb ? (hdr.judgment_ok ? 'Accept' : '') : 'OK';
    const nextRejectReason = isRejectSelected ? (hdr.reject_reason || '') : '';
    setEditHeader(headerData);
    setFinalJudgment(nextJudgment);
    setRejectReason(nextRejectReason);

    // Initialize observations
    const obsMap = {};
    if (isKsb || isCrompton) obsMap[16] = rData.sample_serials;
    (rData.checkpoints || []).forEach(cp => {
      obsMap[cp.row_index] = { ...cp.observations };
    });
    setEditObservations(obsMap);
  };

  useEffect(() => {
    loadJobData();
  }, [jobId, reportId, activeUnitIndex]);

  useEffect(() => {
    publishUnsavedChanges(false);
    return () => publishUnsavedChanges(false);
  }, []);

  // Handle single observation change
  const handleObservationChange = (rowIndex, col, value) => {
    setEditObservations(prev => ({
      ...prev,
      [rowIndex]: {
        ...(prev[rowIndex] || {}),
        [col]: value
      }
    }));
  };

  const handleDownloadReports = async () => {
    if (!reportsList.length || downloading) return;
    setDownloading(true);
    setErrorMsg('');
    try {
      const downloads = await Promise.all(reportsList.map(async (report) => ({
        report,
        blob: await api.downloadPdfReport(report.id),
      })));

      downloads.forEach(({ report, blob }) => {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `${report.report_code || `report-${report.id}`}.pdf`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      });
    } catch (err) {
      setErrorMsg(err.message || 'Failed to download reports');
    } finally {
      setDownloading(false);
    }
  };

  // Approve report
  const applyStgUpdate = (id, savedReport) => {
    setCurrentReport(report => report?.id === id ? {
      ...report, revision: savedReport.revision, report_data: savedReport.report_data,
    } : report);
  };

  const saveStgPhoto = async (slot, photo) => {
    const { id, revision } = currentReport;
    setStgSaving(true);
    try {
      applyStgUpdate(id, await api.saveReportPhoto(id, slot, revision, photo));
    } finally {
      setStgSaving(false);
    }
  };

  const saveStgFields = async () => {
    const { id, revision } = currentReport;
    setStgSaving(true);
    setErrorMsg('');
    try {
      applyStgUpdate(id, await api.updateReport(id, { expected_revision: revision, header_data: editHeader }));
      publishUnsavedChanges(false);
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setStgSaving(false);
    }
  };

  const handleApprove = async () => {
    if (!currentReport || approving || stgSaving) return;
    setApproving(true);
    setErrorMsg('');
    try {
      const savedReport = await api.updateReport(currentReport.id, {
        expected_revision: currentReport.revision,
        header_data: editHeader,
        observation_readings: editObservations,
        ...(currentReport.report_data?.primary_sheet !== 'Falcon PDI' && { final_judgment: finalJudgment }),
        reject_reason: rejectReason
      });
      await api.approveReport(currentReport.id, savedReport.revision);
      publishUnsavedChanges(false);

      const updatedJob = await api.getJobDetails(job.id);
      setJob(updatedJob);
      setLegalChecklist(updatedJob.legal_checklist || null);
      const nextReport = updatedJob.reports?.find(
        report => !['Approved', 'Emailed'].includes(report.status)
      );
      if (nextReport) {
        setActiveUnitIndex(nextReport.unit_index);
        return;
      }

      if (
        String(updatedJob.company_name).trim().toLowerCase() === 'havells' &&
        updatedJob.legal_status !== 'Agreed'
      ) {
        if (!updatedJob.legal_checklist?.items?.length) {
          throw new Error('The J1 legal checklist is unavailable for this model.');
        }
        setShowLegalReview(true);
        return;
      }

      const updatedModelJobs = updatedJob.model_jobs || [];
      const currentModelIndex = updatedModelJobs.findIndex(modelJob => modelJob.id === updatedJob.id);
      const nextModelJob = currentModelIndex >= 0 ? updatedModelJobs[currentModelIndex + 1] : null;
      if (nextModelJob) {
        setActiveUnitIndex(1);
        setSelectedJobId(nextModelJob.id);
        return;
      }

      await loadJobData();
    } catch (err) {
      setErrorMsg(err.message || 'Failed to save and approve report');
    } finally {
      setApproving(false);
    }
  };

  const handleLegalAgree = async (payload) => {
    if (!job || approving) return;
    setApproving(true);
    try {
      await api.agreeLegalChecklist(job.id, payload);
      publishUnsavedChanges(false);
      const updatedJob = await api.getJobDetails(job.id);
      setJob(updatedJob);
      setLegalChecklist(updatedJob.legal_checklist || null);
      setShowLegalReview(false);

      const updatedModelJobs = updatedJob.model_jobs || [];
      const currentModelIndex = updatedModelJobs.findIndex(modelJob => modelJob.id === updatedJob.id);
      const nextModelJob = currentModelIndex >= 0 ? updatedModelJobs[currentModelIndex + 1] : null;
      if (nextModelJob) {
        setActiveUnitIndex(1);
        setSelectedJobId(nextModelJob.id);
        return;
      }

      await loadJobData();
    } finally {
      setApproving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px] space-y-3">
        <Loader2 className="w-8 h-8 text-red-600 animate-spin" />
        <span className="text-sm text-gray-500 font-medium">Loading inspection report workbook...</span>
      </div>
    );
  }

  if (showLegalReview && job) {
    return (
      <div onChange={() => publishUnsavedChanges(true)}>
        <LegalChecklistReview
          job={job}
          checklist={legalChecklist}
          onAgree={handleLegalAgree}
        />
      </div>
    );
  }

  const reportsList = job?.reports || (currentReport ? [currentReport] : []);
  const modelJobs = job?.model_jobs || [];
  const checkpoints = currentReport?.report_data?.checkpoints || [];
  const isFalcon = currentReport?.report_data?.primary_sheet === 'Falcon PDI';
  const isKsb = currentReport?.report_data?.primary_sheet === 'KSB PDI FORMAT';
  const isCrompton = currentReport?.report_data?.primary_sheet === CROMPTON_SHEET;
  const isStg = currentReport?.report_data?.format === 'docx';
  const stgReadOnly = ['Approved', 'Emailed'].includes(currentReport?.status);
  const stgInput = (key, label) => (
    <input aria-label={label} type="text" value={editHeader[key] || ''} maxLength={180}
      onChange={event => setEditHeader({ ...editHeader, [key]: event.target.value })}
      disabled={stgReadOnly || stgSaving || approving}
      className="block w-full bg-transparent px-2 py-1 text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-600"
    />
  );
  const firstObservationNumber = ((currentReport?.unit_index || 1) - 1) * 5 + 1;
  const observationColumnNumbers = Array.from(
    { length: 5 },
    (_, index) => firstObservationNumber + index
  );

  return (
    <div className="space-y-6" onChange={() => publishUnsavedChanges(true)}>
      
      {/* Top Breadcrumb & Job Header */}
      <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm space-y-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center space-x-3">
            <button
              onClick={() => setActiveTab('dashboard')}
              className="p-2 border rounded-lg hover:bg-gray-100 text-gray-600 transition"
              title={backLabel}
            >
              <ArrowLeft className="w-4 h-4" />
            </button>
            <div>
              <div className="flex items-center space-x-2">
                <span className="font-mono text-xs bg-gray-100 text-gray-700 font-bold px-2 py-0.5 rounded">
                  {job?.job_code || currentReport?.report_code}
                </span>
                <span className="text-xs bg-blue-100 text-blue-800 font-extrabold px-2 py-0.5 rounded">
                  {job?.company_name ? `${job.company_name.toUpperCase()} OEM FORMAT` : 'CUSTOMER OEM FORMAT'}
                </span>
                <span className="text-xs font-semibold px-2 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200">
                  {job?.status || currentReport?.status}
                </span>
              </div>
              <h1 className="text-xl font-bold text-gray-900 mt-1">
                {job?.model_name || job?.product_type || 'Surface Pump'} — {reportsList.length} Individual Report(s)
              </h1>
            </div>
          </div>

          {/* Action Toolbar */}
          <div className="flex flex-wrap items-center gap-2">
            {currentReport && (isKsb || job?.company_name?.trim().toLowerCase() === 'havells') && (
              <a href={api.getExcelDownloadUrl(currentReport.id)} className="inline-flex items-center gap-1.5 rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-xs font-semibold text-green-700">
                <Download className="h-3.5 w-3.5" /> Download Excel report
              </a>
            )}
            {isStg ? (
              <a href={api.getDocumentDownloadUrl(currentReport.id)} className="inline-flex items-center gap-1.5 rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-xs font-semibold text-green-700">
                <Download className="h-3.5 w-3.5" /> Download Word report
              </a>
            ) : reportsList.length > 0 && (
              <button
                type="button"
                onClick={handleDownloadReports}
                disabled={downloading}
                className="flex items-center space-x-1.5 text-xs font-semibold bg-green-50 text-green-700 border border-green-200 hover:bg-green-100 disabled:opacity-60 px-3 py-2 rounded-lg transition"
              >
                {downloading
                  ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  : <Download className="w-3.5 h-3.5" />}
                <span>{downloading ? 'Downloading...' : isCrompton ? 'Download PDF report' : 'Download'}</span>
              </button>
            )}

            {!isStg && <button
              onClick={() => setIsPrintOpen(true)}
              className="flex items-center space-x-1.5 text-xs font-semibold bg-indigo-600 hover:bg-indigo-700 text-white px-3 py-2 rounded-lg shadow transition"
            >
              <Printer className="w-3.5 h-3.5" />
              <span>Open PDFs to print</span>
            </button>}

            <button
              onClick={() => setIsEmailOpen(true)}
              className="flex items-center space-x-1.5 text-xs font-semibold bg-purple-600 hover:bg-purple-700 text-white px-3 py-2 rounded-lg shadow transition"
            >
              <Mail className="w-3.5 h-3.5" />
              <span>Send Email</span>
            </button>
          </div>
        </div>

        {modelJobs.length > 1 && (
          <div className="pt-3 border-t">
            <label className="block text-xs font-bold text-gray-500 uppercase tracking-wider">
              Models and their reports
              <select
                value={job?.id || ''}
                  onChange={(event) => {
                    setSelectedJobId(Number(event.target.value));
                  setActiveTab('job-review');
                }}
                className="mt-1 block w-full sm:max-w-2xl px-3 py-2 text-sm font-semibold normal-case text-gray-800 bg-white border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {modelJobs.map(modelJob => (
                  <option key={modelJob.id} value={modelJob.id}>
                    {modelJob.model_name || modelJob.product_number || 'Model'} — SKU {modelJob.product_number || '—'} — PO {modelJob.po_number || '—'} — Lot {modelJob.lot_size} — {modelJob.total_reports} report(s)
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}

        {/* Individual Lot Unit Tabs */}
        {reportsList.length > 1 && (
          <div className="pt-3 border-t flex items-center space-x-2 overflow-x-auto pb-1">
            <span className="text-xs font-bold text-gray-500 uppercase mr-1">Lot Units:</span>
            {reportsList.map((r) => (
              <button
                key={r.id}
                onClick={() => {
                  setActiveUnitIndex(r.unit_index);
                  initReportForm(r);
                }}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition shrink-0 ${
                  r.unit_index === activeUnitIndex
                    ? 'bg-red-600 text-white shadow'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                Unit #{r.unit_index} ({r.report_code})
              </button>
            ))}
          </div>
        )}
      </div>

      {errorMsg && (
        <div className="p-4 bg-red-50 text-red-800 text-sm rounded-xl border border-red-200 flex items-center space-x-2">
          <AlertCircle className="w-5 h-5 shrink-0 text-red-600" />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* Excel Sheet Simulator & Editor */}
      <div className="bg-white rounded-xl border border-gray-300 shadow-sm overflow-hidden">
        
        {/* Sheet Top Banner mimicking official Havells sheet header */}
        {!isStg && <div className="bg-gray-100 p-4 border-b border-gray-300 flex flex-col md:flex-row md:items-center justify-between text-xs gap-3">
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 rounded bg-red-600 text-white font-bold flex items-center justify-center text-sm shadow">
              {isCrompton ? 'CG' : isKsb ? 'KSB' : 'H'}
            </div>
            <div>
              <div className="font-extrabold text-gray-900 text-sm">
                {isKsb || isCrompton ? currentReport.report_data.header_data.title : 'Pump - Pre-dispatch Inspection Report'}
              </div>
            </div>
          </div>
          <div className="flex items-center space-x-3 font-semibold text-gray-700">
            <span>Status: <b>{currentReport?.status}</b></span>
            <span>•</span>
            <span>Unit: <b>#{currentReport?.unit_index} of {reportsList.length}</b></span>
          </div>
        </div>}

        {isStg ? (
          <div className="mx-auto max-w-5xl p-3 text-black sm:p-6">
            <div className="mb-3 flex items-end justify-between gap-3">
              <h2 className="text-base font-medium sm:text-2xl">STERLING SITES – Product Inspection Report</h2>
              <img src={sterlingLogo} alt="Sterling Sites" className="w-12 shrink-0 sm:w-16" />
            </div>
            <table className="stg-format-table">
              <colgroup><col className="w-[22%]" /><col className="w-[38%]" /><col className="w-[15%]" /><col /></colgroup>
              <tbody>
                <tr><th>PO Number</th><td>{stgInput('po_number', 'PO Number')}</td><th>POD</th><td>{stgInput('pod', 'POD')}</td></tr>
                <tr><th>PI Number</th><td>{stgInput('pi_number', 'PI Number')}</td><th>Batch Number</th><td>{stgInput('batch_number', 'Batch Number')}</td></tr>
                <tr><th>Vendor name</th><td className="px-2" colSpan={3}>YATHI PUMPS</td></tr>
                <tr><th>Date</th><td>{stgInput('inspection_date', 'Date')}</td><th>Sterling Doc No.</th><td className="px-2">SITES/QC/100 Rev.0</td></tr>
              </tbody>
            </table>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs text-gray-700">Add photos in the matching cells, then download the Word report.</p>
              {!stgReadOnly && <button type="button" onClick={saveStgFields} disabled={stgSaving || approving} className="rounded border border-gray-300 px-3 py-2 text-xs font-semibold disabled:opacity-50">Save report details</button>}
            </div>
            <StgPhotoSlots key={currentReport.id} report={currentReport} modelInput={stgInput('model_name', 'Item 1 Name')}
              disabled={stgSaving || approving} onSave={saveStgPhoto} />
          </div>
        ) : (
        <>
        {/* Permitted Header Fields Grid */}
        <div className="p-5 border-b border-gray-200 bg-gray-50/50">
          <div className="text-xs font-bold uppercase tracking-wider text-gray-500 mb-3">
            Inspection Metadata & Header Parameters
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4 text-xs">
            
            {!isCrompton && <div>
              <label className="text-gray-500 font-medium">Supplier Code / Name</label>
              <div className="mt-1 w-full border rounded p-1.5 bg-gray-100 text-xs font-semibold text-gray-700">{SUPPLIER_NAME}</div>
            </div>}

            {!isCrompton && <div>
              <label className="text-gray-500 font-medium">Supplier Location</label>
              <div className="mt-1 w-full border rounded p-1.5 bg-gray-100 text-xs text-gray-700">{SUPPLIER_LOCATION}</div>
            </div>}

            {!isKsb && <div>
              <label className="text-gray-500 font-medium">SKU No.</label>
              <input
                type="text"
                value={editHeader.sku_no}
                onChange={(e) => setEditHeader({ ...editHeader, sku_no: e.target.value })}
                className="mt-1 w-full border rounded p-1.5 bg-white text-xs font-semibold focus:outline-none focus:ring-1 focus:ring-red-500"
              />
            </div>}

            <div>
              <label className="text-gray-500 font-medium">Model Name</label>
              <input
                type="text"
                value={editHeader.model_name}
                onChange={(e) => setEditHeader({ ...editHeader, model_name: e.target.value })}
                className="mt-1 w-full border rounded p-1.5 bg-white text-xs focus:outline-none focus:ring-1 focus:ring-red-500"
              />
            </div>

            {!isKsb && <div>
              <label className="text-gray-500 font-medium">PO Number</label>
              <input
                type="text"
                value={editHeader.po_number}
                onChange={(e) => setEditHeader({ ...editHeader, po_number: e.target.value })}
                className="mt-1 w-full border rounded p-1.5 bg-white text-xs focus:outline-none focus:ring-1 focus:ring-red-500"
              />
            </div>}

            <div>
              <label className="text-gray-500 font-medium">{isCrompton ? 'Tested By' : 'Inspected By'}</label>
              <input
                type="text"
                value={editHeader.inspected_by}
                onChange={(e) => setEditHeader({ ...editHeader, inspected_by: e.target.value })}
                className="mt-1 w-full border rounded p-1.5 bg-white text-xs focus:outline-none focus:ring-1 focus:ring-red-500"
              />
            </div>

            <div>
              <label className="text-gray-500 font-medium">Approved By</label>
              <input
                type="text"
                value={editHeader.approved_by}
                onChange={(e) => setEditHeader({ ...editHeader, approved_by: e.target.value })}
                className="mt-1 w-full border rounded p-1.5 bg-white text-xs focus:outline-none focus:ring-1 focus:ring-red-500"
              />
            </div>

            {(isFalcon || isKsb || isCrompton) && (
              <div>
                <div className="text-gray-500 font-medium">{isKsb || isCrompton ? 'Lot Size' : 'Actual Quantity'}</div>
                <div className="mt-1 w-full border rounded p-1.5 bg-gray-100 text-xs">{editHeader.lot_qty}</div>
              </div>
            )}
            {isFalcon && [
              ['power_rating', 'HP/KW'],
              ['incoming_date', 'Incoming Date'],
              ['inspection_date', 'Date of Report'],
              ['invoice_number', 'Invoice Number'],
              ['prepared_by', 'Prepared By'],
            ].map(([key, label]) => (
              <label key={key} className="text-gray-500 font-medium">
                {label}
                <input
                  type="text"
                  value={editHeader[key] || ''}
                  onChange={event => setEditHeader({ ...editHeader, [key]: event.target.value })}
                  className="mt-1 w-full border rounded p-1.5 bg-white text-xs focus:outline-none focus:ring-1 focus:ring-red-500"
                />
              </label>
            ))}
            {(isCrompton ? CROMPTON_FIELDS : isKsb ? [
              ['inspection_date', 'Date of Inspection'],
              ['lot_dispatch_date', 'Date of Dispatch'],
              ['special_remarks', 'Report Remarks'],
            ] : []).map(([key, label]) => (
              <label key={key} className="text-gray-500 font-medium">
                {label}
                <input
                  value={editHeader[key] || ''}
                  onChange={event => setEditHeader({ ...editHeader, [key]: event.target.value })}
                  className="mt-1 w-full rounded border bg-white p-1.5 text-xs"
                />
              </label>
            ))}
            {(isKsb || isCrompton) && (
              <label className="text-gray-500 font-medium">
                Decision on the Lot
                <select value={finalJudgment} onChange={event => setFinalJudgment(event.target.value)}
                  className="mt-1 w-full rounded border bg-white p-1.5 text-xs">
                  <option value="">Select a decision</option>
                  {(isCrompton ? CROMPTON_DECISIONS : ['Accept', 'Reject']).map(decision => (
                    <option key={decision} value={decision}>{decision}</option>
                  ))}
                </select>
              </label>
            )}
            {isCrompton && (
              <label className="col-span-full text-gray-500 font-medium">
                Note
                <textarea value={editHeader.note || ''} rows={3}
                  onChange={event => setEditHeader({ ...editHeader, note: event.target.value })}
                  className="mt-1 w-full rounded border bg-white p-1.5 text-xs" />
              </label>
            )}
          </div>
        </div>

        {isKsb || isCrompton ? (
          <KsbObservations columns={currentReport.report_data.sample_columns} checkpoints={checkpoints}
            readings={editObservations} onChange={handleObservationChange}
            sampleLabel={isCrompton ? 'Unit' : 'Sample'} methodLabel={isCrompton ? 'Parameter type' : undefined} />
        ) : isFalcon ? (
          <div className="overflow-x-auto max-h-[500px]">
            <table className="w-full text-left border-collapse text-sm">
              <thead className="sticky top-0 bg-gray-800 text-white">
                <tr>
                  <th scope="col" className="py-2 px-4">Inspection Check</th>
                  <th scope="col" className="py-2 px-4 w-40">Remarks</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {checkpoints.map(checkpoint => (
                  <tr key={checkpoint.row_index}>
                    <th scope="row" className="py-2 px-4 font-medium">{checkpoint.parameter}</th>
                    <td className="py-2 px-4">
                      <select
                        aria-label={checkpoint.parameter}
                        value={editObservations[checkpoint.row_index]?.G || ''}
                        onChange={event => handleObservationChange(checkpoint.row_index, 'G', event.target.value)}
                        className="w-full border rounded bg-white p-1.5"
                      >
                        <option value="">Select</option>
                        <option value="OK">OK</option>
                        <option value="NOT OK">NOT OK</option>
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
        <div className="overflow-x-auto max-h-[500px]">
          <table className="w-full min-w-[1260px] text-left border-collapse text-xs">
            <thead className="sticky top-0 bg-gray-800 text-white z-10">
              <tr>
                <th rowSpan={2} className="py-2.5 px-3 border border-gray-700 text-center w-12 align-middle">S.N.</th>
                <th rowSpan={2} className="py-2.5 px-3 border border-gray-700 w-36 align-middle">Inspection Type</th>
                <th rowSpan={2} className="py-2.5 px-3 border border-gray-700 w-48 align-middle">Parameter</th>
                <th rowSpan={2} className="py-2.5 px-3 border border-gray-700 w-64 align-middle">Specification</th>
                <th rowSpan={2} className="py-2.5 px-3 border border-gray-700 w-28 align-middle">Method</th>
                <th rowSpan={2} className="py-2.5 px-3 border border-gray-700 w-28 align-middle">Frequency</th>
                <th colSpan={5} className="py-2.5 px-3 border border-gray-700 bg-red-950/70 text-center">
                  Observation
                </th>
              </tr>
              <tr>
                {observationColumnNumbers.map((sampleNumber) => (
                  <th
                    key={sampleNumber}
                    className="py-2 px-2 border border-gray-700 bg-red-950/70 text-center w-20 min-w-[5rem]"
                  >
                    {sampleNumber}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {checkpoints.map((cp) => {
                const obs = editObservations[cp.row_index] || cp.observations || {};
                const isMulti = cp.is_multi_sample;

                return (
                  <tr key={cp.row_index} className="hover:bg-amber-50/30 transition">
                    <td className="py-2 px-3 border border-gray-200 text-center font-bold text-gray-600 bg-gray-50/50">
                      {cp.item_sn}
                    </td>
                    <td className="py-2 px-3 border border-gray-200 font-semibold text-gray-700 bg-gray-50/30">
                      {cp.inspection_type}
                    </td>
                    <td className="py-2 px-3 border border-gray-200 font-medium text-gray-900">
                      {cp.parameter}
                    </td>
                    <td className="py-2 px-3 border border-gray-200 text-gray-600 text-[11px]">
                      {cp.specification}
                    </td>
                    <td className="py-2 px-3 border border-gray-200 text-gray-500 text-[11px]">
                      {cp.method}
                    </td>
                    <td className="py-2 px-3 border border-gray-200 text-gray-500 text-[11px]">
                      {cp.frequency}
                    </td>
                    
                    {/* Observation input(s) */}
                    {isMulti ? (
                      ['G', 'H', 'I', 'J', 'K'].map((colKey, sampleIndex) => (
                        <td key={colKey} className="py-1 px-2 border border-gray-200 bg-white w-20 min-w-[5rem]">
                          <input
                            type="text"
                            value={obs[colKey] || ''}
                            onChange={(e) => handleObservationChange(cp.row_index, colKey, e.target.value)}
                            title={`Sample #${observationColumnNumbers[sampleIndex]} (Col ${colKey})`}
                            className="w-full text-[11px] p-1 border rounded bg-gray-50/50 text-center focus:bg-white focus:outline-none focus:ring-1 focus:ring-red-500 font-mono"
                          />
                        </td>
                      ))
                    ) : (
                      <td colSpan={5} className="py-1 px-2 border border-gray-200 bg-white">
                        <input
                          type="text"
                          value={obs['G'] || ''}
                          onChange={(e) => handleObservationChange(cp.row_index, 'G', e.target.value)}
                          className="w-full text-xs p-1.5 border rounded bg-gray-50/40 focus:bg-white focus:outline-none focus:ring-1 focus:ring-red-500 font-medium"
                        />
                      </td>
                    )}

                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        )}
        </>
        )}

        {/* Bottom Save & Approve Bar */}
        <div className="p-4 bg-gray-50 border-t border-gray-300 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="text-xs text-gray-500">
            {isStg ? (
              <p>{stgSaving ? 'Saving to the Word report…' : 'Open the downloaded Word report to print it.'}</p>
            ) : isFalcon ? (
              <p>Select OK or NOT OK for each Falcon check after completing the inspection.</p>
            ) : isCrompton ? (
              <p>Enter the serial numbers and actual test values for the units you inspected.</p>
            ) : (
              <p>Fixed inspection criteria and company-defined standards cannot be modified. All edits are validated against IS tolerances.</p>
            )}
            {!isStg && <p className="mt-1 font-semibold text-amber-700">Edits are saved when you approve the report.</p>}
          </div>

          <div className="flex items-center space-x-3">
            {!(isStg && stgReadOnly) && <button
              onClick={handleApprove}
              disabled={approving || stgSaving}
              className="flex items-center space-x-1.5 bg-green-600 hover:bg-green-700 disabled:cursor-not-allowed disabled:opacity-60 text-white px-5 py-2 rounded-lg text-xs font-bold transition shadow"
            >
              {approving ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
              <span>{approving ? 'Saving & Approving...' : 'Approve Report'}</span>
            </button>}
          </div>
        </div>

      </div>

      {/* Host Print Dialog */}
      <PrintDialog
        isOpen={isPrintOpen}
        onClose={() => setIsPrintOpen(false)}
        jobId={job?.id}
        reportId={currentReport?.id}
      />

      {/* Customer Email Dialog */}
      <EmailDialog
        isOpen={isEmailOpen}
        onClose={() => setIsEmailOpen(false)}
        job={job}
        onReviewPdiReports={(pendingJobId) => {
          setIsEmailOpen(false);
          if (pendingJobId && Number(pendingJobId) !== Number(job?.id)) {
            setActiveUnitIndex(1);
            setSelectedJobId(pendingJobId);
            setActiveTab('job-review');
            return;
          }
          const pendingReport = job?.reports?.find(
            report => !['Approved', 'Emailed'].includes(report.status)
          );
          if (pendingReport && pendingReport.unit_index !== activeUnitIndex) {
            setActiveUnitIndex(pendingReport.unit_index);
          }
          setErrorMsg('Approve every PDI report for every model before emailing the inspection batch.');
        }}
        onReviewLegal={(pendingJobId) => {
          setIsEmailOpen(false);
          if (pendingJobId && Number(pendingJobId) !== Number(job?.id)) {
            setActiveUnitIndex(1);
            setSelectedJobId(pendingJobId);
            setActiveTab('job-review');
            return;
          }
          setShowLegalReview(true);
        }}
        onEmailSuccess={() => {
          setIsEmailOpen(false);
          loadJobData();
        }}
      />

    </div>
  );
}
