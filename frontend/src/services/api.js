const API_BASE = '/api';

export const getConnectionMessage = () => {
  const hostname = window.location.hostname;
  if (['localhost', '127.0.0.1', '[::1]'].includes(hostname)) {
    return 'Cannot reach the local PDI server. Start the server and try again.';
  }
  return 'Cannot reach the PDI server. Check your connection to the server and try again.';
};

const apiFetch = async (...args) => {
  try {
    return await fetch(...args);
  } catch {
    throw new Error(getConnectionMessage());
  }
};

const parseApiResponse = async (response, action) => {
  const responseText = await response.text();
  let responseData;
  try {
    responseData = responseText ? JSON.parse(responseText) : {};
  } catch {
    if (!response.ok) {
      const detail = responseText.trim().slice(0, 200) || response.statusText;
      throw new Error(`${action} failed (${response.status}): ${detail}`);
    }
    throw new Error(`${action} returned an invalid non-JSON response (${response.status}).`);
  }

  if (!response.ok) {
    throw new Error(
      responseData.detail || responseData.error || `${action} failed (${response.status})`
    );
  }
  return responseData;
};

const parseDownloadResponse = async (response, action, fallbackFilename) => {
  if (!response.ok) {
    await parseApiResponse(response, action);
  }
  const disposition = response.headers.get('Content-Disposition') || '';
  const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] || fallbackFilename;
  return { blob: await response.blob(), filename };
};

export const api = {
  // Authentication
  getCurrentUser: async () => {
    const res = await apiFetch(`${API_BASE}/auth/me`);
    return parseApiResponse(res, 'Session check');
  },
  getSetupStatus: async () => {
    const res = await apiFetch(`${API_BASE}/auth/setup/status`);
    return parseApiResponse(res, 'Administrator setup check');
  },
  login: async (email, password) => {
    const res = await apiFetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    return parseApiResponse(res, 'Login');
  },
  logout: async () => {
    const res = await apiFetch(`${API_BASE}/auth/logout`, { method: 'POST' });
    return parseApiResponse(res, 'Logout');
  },
  getUsers: async () => {
    const res = await apiFetch(`${API_BASE}/auth/users`);
    return parseApiResponse(res, 'Employee list request');
  },
  createUser: async (payload) => {
    const res = await apiFetch(`${API_BASE}/auth/users`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return parseApiResponse(res, 'Employee creation');
  },
  setUserActive: async (userId, isActive) => {
    const res = await apiFetch(`${API_BASE}/auth/users/${userId}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: isActive }),
    });
    return parseApiResponse(res, 'Employee status update');
  },
  downloadBackup: async () => {
    const res = await apiFetch(`${API_BASE}/admin/backup`);
    return parseDownloadResponse(res, 'Backup download', 'yathi-pdi-backup.zip');
  },
  downloadExcelData: async () => {
    const res = await apiFetch(`${API_BASE}/admin/backup/excel`);
    return parseDownloadResponse(res, 'Excel data download', 'PDI Data.xlsx');
  },
  importBackup: async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await apiFetch(`${API_BASE}/admin/import`, {
      method: 'POST',
      body: formData,
    });
    return parseApiResponse(res, 'Backup import');
  },

  // Health
  checkHealth: async () => {
    const res = await apiFetch(`${API_BASE}/health`);
    return parseApiResponse(res, 'Health check');
  },
  getVersion: async () => {
    const res = await apiFetch(`${API_BASE}/version`);
    return parseApiResponse(res, 'Version request');
  },

  // AI assistant
  sendChatMessage: async (messages, context = {}) => {
    const res = await apiFetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages, ...context }),
    });
    return parseApiResponse(res, 'AI chat request');
  },
  parseChatReportRequest: async (messages) => {
    const res = await apiFetch(`${API_BASE}/chat/parse-report-request`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages }),
    });
    return parseApiResponse(res, 'Report requirement extraction');
  },
  downloadDailyComparisonPdf: async () => {
    const res = await apiFetch(`${API_BASE}/chat/reports/daily-comparison.pdf`);
    return parseDownloadResponse(res, 'PDF generation', 'pdi_daily_comparison.pdf');
  },
  analyzeUploadedReport: async (file, outputFormat) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('output_format', outputFormat);
    const res = await apiFetch(`${API_BASE}/chat/analyze-report`, {
      method: 'POST',
      body: formData,
    });
    const extension = outputFormat === 'both' ? 'zip' : outputFormat;
    return parseDownloadResponse(res, 'Report analysis', `pdi_report_analysis.${extension}`);
  },
  analyzeExistingReports: async (requestText, outputFormat) => {
    const res = await apiFetch(`${API_BASE}/chat/analyze-existing-reports`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_text: requestText, output_format: outputFormat }),
    });
    const extension = outputFormat === 'both' ? 'zip' : outputFormat;
    return parseDownloadResponse(res, 'Report analysis', `pdi_report_analysis.${extension}`);
  },

  // Dashboard
  getDashboardStats: async () => {
    const res = await apiFetch(`${API_BASE}/dashboard/stats`);
    return parseApiResponse(res, 'Dashboard data request');
  },
  getCustomerJobs: async (customer) => {
    const query = new URLSearchParams({ customer });
    const res = await apiFetch(`${API_BASE}/dashboard/customer-jobs?${query}`);
    return parseApiResponse(res, 'Customer inspection reports');
  },

  // Requirements & Extraction
  uploadRequirement: async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await apiFetch(`${API_BASE}/requirements/upload`, {
      method: 'POST',
      body: formData,
    });
    return parseApiResponse(res, 'Requirement upload');
  },

  extractDetails: async (data) => {
    const formData = new FormData();
    if (data.requirement_id) formData.append('requirement_id', data.requirement_id);
    if (data.company_name) formData.append('company_name', data.company_name);
    if (data.product_type) formData.append('product_type', data.product_type);
    if (data.product_number) formData.append('product_number', data.product_number);
    if (data.lot_size) formData.append('lot_size', data.lot_size);
    if (data.customer_name) formData.append('customer_name', data.customer_name);
    if (data.customer_email) formData.append('customer_email', data.customer_email);

    const res = await apiFetch(`${API_BASE}/requirements/extract`, {
      method: 'POST',
      body: formData,
    });
    return parseApiResponse(res, 'Requirement extraction');
  },

  // Templates
  getCustomers: async () => {
    const res = await apiFetch(`${API_BASE}/templates/customers`);
    return parseApiResponse(res, 'Customer catalog request');
  },
  getTemplates: async () => {
    const res = await apiFetch(`${API_BASE}/templates`);
    return parseApiResponse(res, 'Template list request');
  },

  uploadTemplate: async (formData) => {
    const res = await apiFetch(`${API_BASE}/templates/upload`, {
      method: 'POST',
      body: formData,
    });
    return parseApiResponse(res, 'Template upload');
  },

  matchTemplate: async (payload) => {
    const res = await apiFetch(`${API_BASE}/templates/match`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return parseApiResponse(res, 'Template match');
  },

  getTemplateMappings: async (templateId) => {
    const res = await apiFetch(`${API_BASE}/templates/${templateId}/mappings`);
    return parseApiResponse(res, 'Template mapping request');
  },

  // Reports
  generateReports: async (payload) => {
    const res = await apiFetch(`${API_BASE}/reports/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return parseApiResponse(res, 'Report generation');
  },

  getJobs: async () => {
    const res = await apiFetch(`${API_BASE}/reports`);
    return parseApiResponse(res, 'Inspection jobs request');
  },

  getJobDetails: async (jobId) => {
    const res = await apiFetch(`${API_BASE}/reports/jobs/${jobId}`);
    return parseApiResponse(res, 'Inspection job details request');
  },

  getReport: async (reportId) => {
    const res = await apiFetch(`${API_BASE}/reports/${reportId}`);
    return parseApiResponse(res, 'Report details request');
  },

  updateReport: async (reportId, payload) => {
    const res = await apiFetch(`${API_BASE}/reports/${reportId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return parseApiResponse(res, 'Report update');
  },

  approveReport: async (reportId, expectedRevision) => {
    const res = await apiFetch(`${API_BASE}/reports/${reportId}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expected_revision: expectedRevision }),
    });
    return parseApiResponse(res, 'Report approval');
  },

  agreeLegalChecklist: async (jobId, payload) => {
    const res = await apiFetch(`${API_BASE}/reports/jobs/${jobId}/legal/agree`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return parseApiResponse(res, 'Legal checklist agreement');
  },

  // Printing & Printers
  // Email
  getEmailConfig: async () => {
    const res = await apiFetch(`${API_BASE}/reports/email/config`);
    return parseApiResponse(res, 'Email settings request');
  },

  sendEmail: async (payload) => {
    const res = await apiFetch(`${API_BASE}/reports/email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return parseApiResponse(res, 'Email request');
  },
  listEmailScans: async (jobId) => {
    const res = await apiFetch(`${API_BASE}/reports/jobs/${jobId}/email-scans`);
    return parseApiResponse(res, 'Load email images');
  },
  uploadEmailScan: async (jobId, image) => {
    const form = new FormData();
    form.append('image', image, image.name || 'capture.jpg');
    const res = await apiFetch(`${API_BASE}/reports/jobs/${jobId}/email-scans`, { method: 'POST', body: form });
    return parseApiResponse(res, 'Add email image');
  },
  getEmailScanUrl: (jobId, scanId) => `${API_BASE}/reports/jobs/${jobId}/email-scans/${scanId}`,
  deleteEmailScan: async (jobId, scanId) => {
    const res = await apiFetch(api.getEmailScanUrl(jobId, scanId), { method: 'DELETE' });
    return parseApiResponse(res, 'Remove email image');
  },

  // Download URLs
  getExcelDownloadUrl: (reportId) => `${API_BASE}/reports/${reportId}/download/excel`,
  getDocumentDownloadUrl: (reportId) => `${API_BASE}/reports/${reportId}/download/document`,
  getReportPhotoUrl: (reportId, slot, revision) =>
    `${API_BASE}/reports/${reportId}/photos/${slot}?revision=${revision}`,
  saveReportPhoto: async (reportId, slot, revision, photo) => {
    const form = new FormData();
    form.append('expected_revision', revision);
    if (photo) form.append('photo', photo, photo.name || 'capture.jpg');
    const response = await apiFetch(`${API_BASE}/reports/${reportId}/photos/${slot}`, {
      method: 'PATCH',
      body: form,
    });
    return parseApiResponse(response, 'Save inspection photo');
  },
  getPdfDownloadUrl: (reportId) => `${API_BASE}/reports/${reportId}/download/pdf`,
  getPdfOpenUrl: (reportId) => `${API_BASE}/reports/${reportId}/open/pdf`,
  getZipDownloadUrl: (jobId) => `${API_BASE}/reports/jobs/${jobId}/download/zip`,
  downloadPdfReport: async (reportId) => {
    const res = await apiFetch(`${API_BASE}/reports/${reportId}/download/pdf`);
    if (!res.ok) {
      throw new Error(`Failed to download report ${reportId}`);
    }
    return res.blob();
  },
};
