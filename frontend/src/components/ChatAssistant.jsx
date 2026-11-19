import React, { useEffect, useRef, useState } from 'react';
import { Bot, LoaderCircle, MessageCircle, Paperclip, Send, Sparkles, X } from 'lucide-react';
import { api } from '../services/api';
import { classifyChatIntent } from '../services/chatIntent';

const STARTER_QUESTIONS = [
  'How do I generate a PDI report?',
  'Which customer templates are available?',
  'How do I capture STG photos?',
];

function renderAnswer(content) {
  return content.replace(/^[ \t]*[-*] +/gm, '• ').split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g).map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith('`') && part.endsWith('`')) return <code key={index} className="rounded bg-slate-100 px-1">{part.slice(1, -1)}</code>;
    return part;
  });
}

export default function ChatAssistant({ screen, jobId, reportId }) {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [selectedFile, setSelectedFile] = useState(null);
  const [pendingDraft, setPendingDraft] = useState(null);
  const [customers, setCustomers] = useState([]);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState('');
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  const downloadUrlsRef = useRef([]);
  const hasDraft = Boolean(pendingDraft);

  useEffect(() => {
    if (isOpen) messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [isOpen, messages, isSending, error]);

  useEffect(() => {
    if (!hasDraft || customers.length) return;
    let active = true;
    api.getCustomers().then(catalog => {
      if (active) setCustomers(catalog);
    }).catch(() => {});
    return () => { active = false; };
  }, [hasDraft, customers.length]);

  useEffect(() => () => {
    downloadUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
  }, []);

  const createDraftFromExtraction = (extracted, requirementId = null) => {
    const extractedModels = Array.isArray(extracted.models) && extracted.models.length
      ? extracted.models
      : Array.isArray(extracted.model_items) && extracted.model_items.length
        ? extracted.model_items
        : [extracted];
    const models = extractedModels.map((model) => ({
      model_name: model.model_name || model.item_name || '',
      product_number: model.product_number || '',
      lot_size: model.lot_size ?? '',
      po_number: model.po_number || extracted.po_number || '',
    }));

    return {
      requirement_id: requirementId,
      company_name: extracted.company_name || extracted.customer_name || '',
      product_type: extracted.product_type || '',
      models: models.length ? models : [{ model_name: '', product_number: '', lot_size: '', po_number: '' }],
    };
  };

  const updateDraftModel = (index, field, value) => {
    setPendingDraft((draft) => ({
      ...draft,
      models: draft.models.map((model, modelIndex) =>
        modelIndex === index ? { ...model, [field]: value } : model
      ),
    }));
  };

  const handleCreateDraftReports = async () => {
    if (!pendingDraft || isSending) return;
    setError('');

    const companyName = pendingDraft.company_name.trim();
    const productType = pendingDraft.product_type.trim()
      || (companyName.toLowerCase() === 'havells' ? 'Surface Pump' : '');
    if (!companyName || !productType) {
      setError('Select a supported customer and enter the product type.');
      return;
    }

    const models = pendingDraft.models.map((model) => ({
      ...model,
      lot_size: String(model.lot_size ?? '').trim()
        ? Number(String(model.lot_size).replace(/,/g, '').trim())
        : NaN,
    }));
    const incompleteModel = models.findIndex((model) =>
      !model.model_name.trim()
      || !model.product_number.trim()
      || !model.po_number.trim()
      || !Number.isInteger(model.lot_size)
      || model.lot_size < (companyName.toLowerCase() === 'crompton' ? 0 : 1)
      || model.lot_size > 1000000
    );
    if (incompleteModel !== -1) {
      setError(`Complete the model name, SKU, PO number, and valid lot size for model ${incompleteModel + 1}.`);
      return;
    }

    setIsSending(true);
    try {
      const generated = [];
      const failures = [];
      for (const model of models) {
        try {
          const match = await api.matchTemplate({
            company_name: companyName,
            product_type: productType,
            product_model: model.model_name,
          });
          if (!match.matched || !match.template_id) {
            throw new Error(match.message || `No active template is available for ${companyName}.`);
          }
          const result = await api.generateReports({
            requirement_id: pendingDraft.requirement_id || undefined,
            template_id: match.template_id,
            company_name: match.customer_name || companyName,
            product_type: match.product_type || productType,
            product_number: model.product_number.trim(),
            model_name: model.model_name.trim(),
            lot_size: model.lot_size,
            po_number: model.po_number.trim(),
          });
          if (!Array.isArray(result.reports) || result.reports.length === 0) {
            throw new Error('The server returned no generated reports.');
          }
          generated.push({ model, result });
        } catch (generationError) {
          failures.push(`${model.model_name}: ${generationError.message}`);
        }
      }

      if (!generated.length) {
        throw new Error(failures.join('\n') || 'No reports were generated.');
      }

      const downloads = generated.flatMap(({ model, result }) =>
        (result.reports || []).flatMap((report) => report.report_data?.format === 'docx' ? [{
          label: `Word - ${report.report_code}`,
          url: api.getDocumentDownloadUrl(report.id),
          filename: `${report.report_code}.docx`,
        }] : [
          {
            label: `Excel - ${report.report_code}`,
            url: api.getExcelDownloadUrl(report.id),
            filename: `${report.report_code}.xlsx`,
          },
          {
            label: `PDF - ${report.report_code}`,
            url: api.getPdfDownloadUrl(report.id),
            filename: `${report.report_code}.pdf`,
          },
        ])
      );
      const reportCount = generated.reduce(
        (total, item) => total + (item.result.reports || []).length,
        0
      );
      const partialFailure = failures.length
        ? `\n\nNot generated:\n${failures.join('\n')}\nDo not resubmit models already created.`
        : '';
      setMessages((previous) => [...previous, {
        role: 'assistant',
        content: `Created ${reportCount} PDI report(s) for ${generated.length} model(s). They are drafts awaiting review. Download the reports below.${partialFailure}`,
        downloads,
      }]);
      setPendingDraft(null);
      setSelectedFile(null);
    } catch (generationError) {
      setError(generationError.message || 'The report drafts could not be created.');
    } finally {
      setIsSending(false);
    }
  };

  const sendMessage = async (event, suggestedQuestion) => {
    event.preventDefault();
    const content = (suggestedQuestion || input).trim();
    const fileToProcess = selectedFile;
    if ((!content && !fileToProcess) || isSending) return;

    const userContent = content || `I attached a file: ${fileToProcess.name}`;
    const nextMessages = [...messages, { role: 'user', content: userContent }];
    setMessages(nextMessages);
    setInput('');
    setError('');
    setIsSending(true);

    if (!content && fileToProcess) {
      setMessages([...nextMessages, {
        role: 'assistant',
        content: 'What would you like me to do with this file? I will not create reports just because a file was attached. Ask me to analyze it or explicitly request draft PDI reports.',
      }]);
      setIsSending(false);
      return;
    }

    try {
      const intent = classifyChatIntent(content, Boolean(fileToProcess));
      const history = nextMessages.slice(-11).map(({ role, content }) => ({ role, content: content.slice(0, 3000) }));

      if (intent === 'daily-comparison') {
        const { blob, filename } = await api.downloadDailyComparisonPdf();
        const downloadUrl = URL.createObjectURL(blob);
        downloadUrlsRef.current.push(downloadUrl);
        setMessages([...nextMessages, {
          role: 'assistant',
          content: 'I created the comparison PDF. Use the button below to download it.',
          downloadUrl,
          filename,
        }]);
      } else if (intent === 'report-analysis') {
        const wantsPdf = /\bpdf\b/i.test(content);
        const wantsWord = /\b(?:word|docx|doc)\b/i.test(content);
        const formats = wantsPdf && wantsWord ? ['both'] : [wantsWord ? 'docx' : 'pdf'];
        const downloads = [];
        for (const format of formats) {
          const result = fileToProcess
            ? await api.analyzeUploadedReport(fileToProcess, format)
            : await api.analyzeExistingReports(content, format);
          const url = URL.createObjectURL(result.blob);
          downloadUrlsRef.current.push(url);
          downloads.push({
            label: format === 'both'
              ? 'Download PDF and Word analysis (ZIP)'
              : `Download ${format.toUpperCase()} analysis`,
            url,
            filename: result.filename,
          });
        }
        setMessages([...nextMessages, {
          role: 'assistant',
          content: 'The report analysis is ready to download. It is advisory and does not change or approve the original report.',
          downloads,
        }]);
        setSelectedFile(null);
        if (fileInputRef.current) fileInputRef.current.value = '';
      } else if (intent === 'report-draft') {
        let extracted;
        let requirementId = null;
        if (fileToProcess) {
          const uploaded = await api.uploadRequirement(fileToProcess);
          requirementId = uploaded.requirement_id;
          setSelectedFile(null);
          if (fileInputRef.current) fileInputRef.current.value = '';
          extracted = await api.extractDetails({ requirement_id: requirementId });
        } else {
          extracted = await api.parseChatReportRequest(history);
        }
        setPendingDraft(createDraftFromExtraction(extracted, requirementId));
        setSelectedFile(null);
        if (fileInputRef.current) fileInputRef.current.value = '';
        setMessages([...nextMessages, {
          role: 'assistant',
          content: 'Review and correct the extracted details below, then create the draft reports.',
        }]);
      } else {
        const { answer } = await api.sendChatMessage(history, {
          screen,
          job_id: screen === 'job-review' ? jobId || null : null,
          report_id: screen === 'report-editor' ? reportId || null : null,
        });
        setMessages([...nextMessages, { role: 'assistant', content: answer }]);
      }
    } catch (requestError) {
      setError(requestError.message || 'The assistant could not respond. Please try again.');
    } finally {
      setIsSending(false);
    }
  };

  return (
    <div className="fixed bottom-5 right-5 z-[60]">
      {isOpen && (
        <section
          aria-label="AI chat assistant"
          className="mb-3 flex h-[min(34rem,calc(100vh-7rem))] w-[min(24rem,calc(100vw-2.5rem))] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl"
        >
          <header className="flex items-center justify-between bg-blue-700 px-4 py-3 text-white">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-white/15">
                <Bot className="h-5 w-5" aria-hidden="true" />
              </span>
              <div>
                <h2 className="font-semibold">AI Assistant</h2>
                <p className="text-xs text-blue-100">Ask anything about the app</p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setIsOpen(false)}
              className="rounded-lg p-2 text-blue-100 hover:bg-white/10 hover:text-white"
              aria-label="Close chat"
            >
              <X className="h-5 w-5" aria-hidden="true" />
            </button>
          </header>

          <div className="flex-1 space-y-4 overflow-y-auto bg-slate-50 p-4" aria-live="polite">
            {messages.length === 0 && (
              <div className="flex gap-2">
                <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-700">
                  <Sparkles className="h-4 w-4" aria-hidden="true" />
                </span>
                <div className="max-w-[85%] rounded-2xl rounded-tl-sm bg-white p-3 text-sm text-slate-700 shadow-sm">
                  <p>Ask about reports, templates, approvals, or anything else in PDI.</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {STARTER_QUESTIONS.map(question => (
                      <button key={question} type="button" onClick={event => sendMessage(event, question)}
                        className="rounded-lg border border-blue-100 bg-blue-50 px-2 py-1.5 text-left text-xs text-blue-800 hover:bg-blue-100">
                        {question}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}
            {messages.map((message, index) => (
              <div
                key={`${message.role}-${index}`}
                className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[85%] whitespace-pre-wrap break-words rounded-2xl p-3 text-sm ${
                    message.role === 'user'
                      ? 'rounded-br-sm bg-blue-700 text-white'
                      : 'rounded-tl-sm bg-white text-slate-700 shadow-sm'
                  }`}
                >
                  {message.role === 'assistant' ? renderAnswer(message.content) : message.content}
                  {message.downloadUrl && (
                    <a
                      href={message.downloadUrl}
                      download={message.filename}
                      className="mt-3 inline-flex rounded-lg bg-blue-700 px-3 py-2 font-medium text-white hover:bg-blue-800"
                    >
                      Download PDF
                    </a>
                  )}
                  {message.downloads?.map((download) => (
                    <a
                      key={download.url}
                      href={download.url}
                      download={download.filename}
                      className="mt-2 flex rounded-lg bg-blue-700 px-3 py-2 font-medium text-white hover:bg-blue-800"
                    >
                      {download.label}
                    </a>
                  ))}
                </div>
              </div>
            ))}
            {pendingDraft && (
              <div className="space-y-3 rounded-xl border border-blue-200 bg-white p-3 shadow-sm">
                <p className="text-xs text-slate-600">
                  Verify these details. Generated reports remain drafts until approved.
                </p>
                <label className="block text-xs font-medium text-slate-700">
                  Customer
                  <select
                    value={pendingDraft.company_name}
                    onChange={(event) => setPendingDraft({ ...pendingDraft, company_name: event.target.value })}
                    className="mt-1 w-full rounded-lg border border-slate-300 p-2 text-sm"
                  >
                    <option value="">Select customer</option>
                    {[...new Set([...customers.map(customer => customer.name), pendingDraft.company_name])].filter(Boolean).map(customer => (
                      <option key={customer} value={customer}>{customer}</option>
                    ))}
                  </select>
                </label>
                <label className="block text-xs font-medium text-slate-700">
                  Product type
                  <input
                    value={pendingDraft.product_type}
                    onChange={(event) => setPendingDraft({ ...pendingDraft, product_type: event.target.value })}
                    placeholder="For example, Surface Pump"
                    className="mt-1 w-full rounded-lg border border-slate-300 p-2 text-sm"
                  />
                </label>
                {pendingDraft.models.map((model, index) => (
                  <div key={index} className="space-y-2 rounded-lg bg-slate-50 p-2">
                    <div className="flex items-center justify-between text-xs font-semibold text-slate-700">
                      <span>Model {index + 1}</span>
                      {pendingDraft.models.length > 1 && (
                        <button
                          type="button"
                          disabled={isSending}
                          onClick={() => setPendingDraft({
                            ...pendingDraft,
                            models: pendingDraft.models.filter((_, modelIndex) => modelIndex !== index),
                          })}
                          className="text-red-700 hover:underline disabled:opacity-50"
                        >
                          Remove
                        </button>
                      )}
                    </div>
                    {[
                      ['model_name', 'Model name'],
                      ['product_number', 'SKU / product number'],
                      ['lot_size', 'Lot size'],
                      ['po_number', 'PO number'],
                    ].map(([field, label]) => (
                      <label key={field} className="block text-xs font-medium text-slate-700">
                        {label}
                        <input
                          type={field === 'lot_size' ? 'number' : 'text'}
                          min={field === 'lot_size' ? (pendingDraft.company_name.trim().toLowerCase() === 'crompton' ? 0 : 1) : undefined}
                          value={model[field]}
                          onChange={(event) => updateDraftModel(index, field, event.target.value)}
                          disabled={isSending}
                          className="mt-1 w-full rounded-lg border border-slate-300 p-2 text-sm"
                        />
                      </label>
                    ))}
                  </div>
                ))}
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={isSending}
                    onClick={() => setPendingDraft({
                      ...pendingDraft,
                      models: [...pendingDraft.models, { model_name: '', product_number: '', lot_size: '', po_number: '' }],
                    })}
                    className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                  >
                    Add model
                  </button>
                  <button
                    type="button"
                    onClick={handleCreateDraftReports}
                    disabled={isSending}
                    className="flex-1 rounded-lg bg-blue-700 px-3 py-2 text-xs font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:bg-slate-300"
                  >
                    {isSending ? 'Creating…' : 'Create draft reports'}
                  </button>
                </div>
              </div>
            )}
            {isSending && (
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
                Thinking…
              </div>
            )}
            {error && (
              <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                {error}
              </p>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="border-t border-slate-200 bg-white p-3">
            {selectedFile && (
              <div className="mb-2 flex items-center justify-between rounded-lg bg-blue-50 px-3 py-2 text-xs text-blue-900">
                <span className="truncate">{selectedFile.name}</span>
                <button
                  type="button"
                  onClick={() => {
                    setSelectedFile(null);
                    if (fileInputRef.current) fileInputRef.current.value = '';
                  }}
                  className="ml-2 rounded p-1 hover:bg-blue-100"
                  aria-label="Remove attached requirement"
                >
                  <X className="h-4 w-4" aria-hidden="true" />
                </button>
              </div>
            )}
            <form onSubmit={sendMessage} className="flex items-end gap-2">
              <label htmlFor="assistant-message" className="sr-only">Your message</label>
              <input
                ref={fileInputRef}
                type="file"
                accept=".jpg,.jpeg,.png,.pdf,.xlsx,.xls,.docx"
                className="hidden"
                onChange={(event) => setSelectedFile(event.target.files?.[0] || null)}
                disabled={isSending}
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={isSending}
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-slate-300 text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                aria-label="Attach report, purchase order, or requirement"
                title="Attach report, purchase order, or requirement"
              >
                <Paperclip className="h-4 w-4" aria-hidden="true" />
              </button>
              <textarea
                id="assistant-message"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    event.currentTarget.form?.requestSubmit();
                  }
                }}
                maxLength={3000}
                rows={1}
                placeholder="Ask about the app, or analyze a report and request a PDF/Word download…"
                className="max-h-28 min-h-11 flex-1 resize-y rounded-xl border border-slate-300 px-3 py-2.5 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                disabled={isSending}
              />
              <button
                type="submit"
                disabled={isSending || (!input.trim() && !selectedFile)}
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-700 text-white transition-colors hover:bg-blue-800 disabled:cursor-not-allowed disabled:bg-slate-300"
                aria-label="Send message"
              >
                <Send className="h-4 w-4" aria-hidden="true" />
              </button>
            </form>
            <p className="mt-2 text-center text-[11px] leading-4 text-slate-500">
              Chat and app summaries go to Gemini. Report/requirement contents are sent for requested analysis or extraction. Do not attach credentials.
            </p>
          </div>
        </section>
      )}

      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        className="ml-auto flex h-14 w-14 items-center justify-center rounded-full bg-blue-700 text-white shadow-lg transition hover:scale-105 hover:bg-blue-800 focus:outline-none focus:ring-4 focus:ring-blue-200"
        aria-label={isOpen ? 'Close AI assistant' : 'Open AI assistant'}
        aria-expanded={isOpen}
      >
        {isOpen ? <X className="h-6 w-6" aria-hidden="true" /> : <MessageCircle className="h-6 w-6" aria-hidden="true" />}
      </button>
    </div>
  );
}
