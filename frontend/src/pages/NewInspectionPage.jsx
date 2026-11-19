import React, { useState, useEffect, useRef } from 'react';
import { api } from '../services/api';
import { publishUnsavedChanges } from '../services/dirtyState';
import { 
  UploadCloud, 
  FileCheck, 
  AlertTriangle, 
  CheckCircle2, 
  Sparkles, 
  Layers, 
  Cpu, 
  Loader2, 
  ArrowRight,
  Info,
  Building2,
  ChevronDown,
  ChevronUp,
  Plus,
  Trash2
} from 'lucide-react';

const getReportCount = (lotSize, splitLot) => {
  const qty = Number(lotSize);
  if (!Number.isInteger(qty) || qty < 1) return 0;
  if (!splitLot || qty <= 100) return 1;
  if (qty <= 1200) return 2;
  if (qty <= 2500) return 3;
  if (qty <= 4000) return 4;
  return 5;
};

const customerLabel = customer => customer.code.toLowerCase() === customer.name.toLowerCase()
  ? customer.name
  : `${customer.name} (${customer.code})`;

export default function NewInspectionPage({
  setActiveTab,
  generatedJobs,
  setGeneratedJobs,
  setSelectedReviewJobId,
  setGenerationWarning
}) {
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [extractionFailed, setExtractionFailed] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [additionalModels, setAdditionalModels] = useState([]);
  const [modelsExpanded, setModelsExpanded] = useState(false);
  const [customers, setCustomers] = useState([]);
  const [customerLoadError, setCustomerLoadError] = useState('');
  const selectedCustomerRef = useRef('');
  const matchRequestRef = useRef(0);

  // Start blank: all order data must come from the uploaded requirement or explicit review.
  const [formData, setFormData] = useState({
    requirement_id: null,
    company_name: '',
    product_type: '',
    product_number: '',
    model_name: '',
    lot_size: '',
    customer_name: '',
    customer_email: '',
    supplier_name: '',
    supplier_location: '',
    po_number: '',
    po_total_qty: '',
    inspection_date: '',
    lot_dispatch_date: '',
  });

  const [missingFields, setMissingFields] = useState([]);
  const [uncertainFields, setUncertainFields] = useState([]);
  const splitLot = formData.company_name.trim().toLowerCase() === 'havells';
  const modelEntries = [
    {
      id: 'primary',
      model_name: formData.model_name,
      product_number: formData.product_number,
      lot_size: formData.lot_size,
      po_number: formData.po_number
    },
    ...additionalModels
  ];
  const totalReportCount = modelEntries.reduce(
    (total, model) => total + getReportCount(model.lot_size, splitLot),
    0
  );
  const [templateMatch, setTemplateMatch] = useState({
    matched: false,
    template_id: null,
    template_name: '',
    company_supported: false,
    message: 'Upload a document or select a customer to match its PDI template'
  });
  const selectedCustomer = customers.find(customer => customer.name === formData.company_name);
  const selectableProductTypes = [...new Set(
    (templateMatch.available_templates || [])
      .map(template => String(template.product_type || '').trim())
      .filter(Boolean)
  )];

  const triggerMatch = async (customerName, productType = '', productModel = '') => {
    const requestId = ++matchRequestRef.current;
    setTemplateMatch({ matched: false, template_name: '', message: 'Checking registered templates…' });
    try {
      const matchRes = await api.matchTemplate({
        company_name: customerName,
        product_type: productType,
        product_model: productModel
      });
      if (requestId === matchRequestRef.current) setTemplateMatch(matchRes);
    } catch (err) {
      if (requestId === matchRequestRef.current) {
        setTemplateMatch({ matched: false, template_name: '', message: err.message });
      }
    }
  };

  useEffect(() => {
    let active = true;
    api.getCustomers().then(catalog => {
      if (active) setCustomers(catalog);
    }).catch(error => {
      if (active) setCustomerLoadError(error.message);
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    publishUnsavedChanges(false);
    return () => publishUnsavedChanges(false);
  }, []);

  const handleSelectCustomer = async (customer) => {
    publishUnsavedChanges(true);
    selectedCustomerRef.current = customer;
    if (customer !== formData.company_name) {
      setAdditionalModels([]);
      setGeneratedJobs([]);
      setSelectedReviewJobId('');
      setGenerationWarning('');
    }
    setFormData(prev => ({
      ...prev,
      company_name: customer,
      customer_name: customer,
      product_type: '',
      model_name: ''
    }));
    if (customer && formData.requirement_id) {
      setErrorMsg('');
      setExtractionFailed(false);
      try {
        await extractUploadedRequirement(formData.requirement_id, customer);
      } catch (err) {
        setErrorMsg(err.message);
        setExtractionFailed(true);
        triggerMatch(customer);
      } finally {
        setExtracting(false);
      }
    } else {
      triggerMatch(customer);
    }
  };

  const extractUploadedRequirement = async (requirementId, customerName = formData.company_name) => {
    ++matchRequestRef.current;
    setExtracting(true);
    const extRes = await api.extractDetails({
      requirement_id: requirementId,
      company_name: customerName || undefined
    });
    if (extRes.error) throw new Error(extRes.error);

    const extractedItems = Array.isArray(extRes.model_items)
      ? extRes.model_items.filter(item => item && typeof item === 'object')
      : [];
    const firstItem = extractedItems[0] || {};
    const extractedValues = {
      ...formData,
      requirement_id: requirementId,
      company_name: extRes.company_name ?? extRes.customer_name ?? '',
      product_type: extRes.product_type ?? '',
      product_number: firstItem.product_number ?? extRes.product_number ?? '',
      model_name: firstItem.model_name ?? extRes.model_name ?? '',
      lot_size: firstItem.lot_size ?? extRes.lot_size ?? '',
      customer_name: extRes.customer_name ?? extRes.company_name ?? '',
      customer_email: extRes.customer_email ?? '',
      supplier_name: extRes.supplier_name ?? '',
      supplier_location: extRes.supplier_location ?? '',
      po_number: firstItem.po_number ?? extRes.po_number ?? '',
      po_total_qty: extRes.po_total_qty ?? '',
      inspection_date: '',
      lot_dispatch_date: '',
    };
    setFormData(extractedValues);
    setAdditionalModels(extractedItems.slice(1).map(item => ({
      id: crypto.randomUUID(),
      model_name: item.model_name ?? '',
      product_number: item.product_number ?? '',
      lot_size: item.lot_size ?? '',
      po_number: item.po_number ?? extRes.po_number ?? '',
    })));
    setModelsExpanded(extractedItems.length > 1);

    const requiredImageFields = ['company_name', 'product_type', 'product_number', 'model_name', 'lot_size', 'po_number'];
    setMissingFields((extRes.missing_fields || []).filter(field => requiredImageFields.includes(field)));
    const uncertain = new Set((extRes.uncertain_fields || []).filter(field => requiredImageFields.includes(field)));
    Object.entries(extRes.field_confidence || {}).forEach(([field, level]) => {
      if (requiredImageFields.includes(field) && String(level).toLowerCase() === 'low') uncertain.add(field);
    });
    setUncertainFields([...uncertain]);

    const matchRes = extractedValues.company_name
      ? await api.matchTemplate({
          company_name: extractedValues.company_name,
          product_type: extractedValues.product_type || '',
          product_model: extractedValues.model_name
        })
      : null;
    const availableProductTypes = [...new Set(
      (matchRes?.available_templates || [])
        .map(template => String(template.product_type || '').trim())
        .filter(Boolean)
    )];
    const resolvedProductType = extractedValues.product_type ||
      (availableProductTypes.length === 1 ? availableProductTypes[0] : '');
    if (resolvedProductType && resolvedProductType !== extractedValues.product_type) {
      setFormData({ ...extractedValues, product_type: resolvedProductType });
    }
    if (resolvedProductType && !extractedValues.product_type) {
      setMissingFields(fields => fields.filter(field => field !== 'product_type'));
      setUncertainFields(fields => fields.filter(field => field !== 'product_type'));
    }

    setTemplateMatch(
      matchRes && resolvedProductType
        ? matchRes
        : {
            ...(matchRes || {}),
            matched: false,
            template_id: null,
            template_name: '',
            company_supported: matchRes?.company_supported ?? false,
            message: availableProductTypes.length > 1
              ? 'The customer has multiple product templates. Enter the product type to choose the correct report format.'
              : matchRes?.message || 'Could not match an OEM template from the extracted customer and product.'
          }
    );
    setExtractionFailed(false);
  };

  const handleRetryExtraction = async () => {
    if (!formData.requirement_id) return;
    setErrorMsg('');
    setExtractionFailed(false);
    try {
      await extractUploadedRequirement(formData.requirement_id, formData.company_name);
    } catch (err) {
      setErrorMsg(err.message);
      setExtractionFailed(true);
    } finally {
      setExtracting(false);
    }
  };

  // Handle requirement file upload
  const handleFileChange = async (e) => {
    const selectedFile = e.target.files[0];
    if (!selectedFile) return;
    ++matchRequestRef.current;
    setFile(selectedFile);
    setErrorMsg('');
    setExtractionFailed(false);
    setMissingFields([]);
    setUncertainFields([]);
    setAdditionalModels([]);
    setGeneratedJobs([]);
    setSelectedReviewJobId('');
    setGenerationWarning('');
    setModelsExpanded(false);
    const selectedCustomer = selectedCustomerRef.current || formData.company_name;
    setFormData(prev => ({
      ...prev,
      requirement_id: null,
      company_name: selectedCustomer,
      product_type: '',
      product_number: '',
      model_name: '',
      lot_size: '',
      customer_name: selectedCustomer,
      customer_email: '',
      supplier_name: '',
      supplier_location: '',
      po_number: '',
      po_total_qty: ''
    }));
    setTemplateMatch({
      matched: false,
      template_id: null,
      template_name: '',
      company_supported: false,
      message: selectedCustomer ? 'Reading the uploaded requirement…' : 'Select a customer to extract this order.'
    });

    let uploadedRequirementId = null;
    try {
      setUploading(true);
      const upRes = await api.uploadRequirement(selectedFile);
      uploadedRequirementId = upRes.requirement_id;
      setFormData(prev => ({ ...prev, requirement_id: upRes.requirement_id }));
      setUploading(false);
      const customerForExtraction = selectedCustomerRef.current || selectedCustomer;
      if (customerForExtraction) {
        await extractUploadedRequirement(upRes.requirement_id, customerForExtraction);
      } else {
        setTemplateMatch({
          matched: false,
          template_id: null,
          template_name: '',
          company_supported: false,
          message: 'Select a customer to extract all item names, models, and quantities from this order.'
        });
      }
    } catch (err) {
      setErrorMsg(err.message);
      setExtractionFailed(!!uploadedRequirementId);
    } finally {
      setUploading(false);
      setExtracting(false);
      setGenerating(false);
    }
  };

  const generateJob = async (values, match) => {
    const res = await api.generateReports({
      requirement_id: values.requirement_id,
      template_id: match.template_id,
      company_name: values.company_name,
      product_type: values.product_type,
      product_number: values.product_number,
      model_name: values.model_name,
      lot_size: parseInt(values.lot_size),
      customer_name: values.customer_name,
      customer_email: values.customer_email,
      supplier_name: values.supplier_name,
      supplier_location: values.supplier_location,
      po_number: values.po_number,
      po_total_qty: values.po_total_qty ? parseInt(values.po_total_qty) : null,
      inspection_date: values.inspection_date || null,
      lot_dispatch_date: values.lot_dispatch_date || null,
    });
    return res;
  };

  const updateModelEntry = (index, field, value) => {
    publishUnsavedChanges(true);
    if (index === 0) {
      setFormData(previous => ({ ...previous, [field]: value }));
      return;
    }
    setAdditionalModels(models => models.map((model, modelIndex) =>
      modelIndex === index - 1 ? { ...model, [field]: value } : model
    ));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file || !formData.requirement_id) {
      setErrorMsg('Upload the purchase order or requirement image first. Reports are generated from the uploaded document.');
      return;
    }
    const missingRequired = ['company_name', 'product_type', 'po_number']
      .filter(field => String(formData[field] ?? '').trim() === '');
    if (missingRequired.length) {
      setErrorMsg(`Fill or correct the required details before generating: ${missingRequired.join(', ')}.`);
      return;
    }
    const incompleteModelIndex = modelEntries.findIndex(model =>
      !String(model.model_name ?? '').trim() ||
      !String(model.product_number ?? '').trim() ||
      !String(model.po_number ?? '').trim() ||
      !Number.isInteger(Number(model.lot_size)) ||
      Number(model.lot_size) <= 0
    );
    if (incompleteModelIndex !== -1) {
      setErrorMsg(`Enter a model name, SKU, PO number, and valid lot size for model ${incompleteModelIndex + 1}.`);
      return;
    }
    if (!templateMatch.matched || !templateMatch.template_id) {
      setErrorMsg(`Cannot generate reports: A valid registered PDI template must be matched for customer '${formData.company_name}'.`);
      return;
    }
    try {
      setGenerating(true);
      setErrorMsg('');
      const results = [];
      for (const model of modelEntries) {
        try {
          results.push(await generateJob({
            ...formData,
            model_name: model.model_name,
            product_number: model.product_number,
            lot_size: model.lot_size,
            po_number: model.po_number
          }, templateMatch));
        } catch (err) {
          if (results.length) {
            setGeneratedJobs(results);
            setSelectedReviewJobId(String(results[0].job_id));
            setGenerationWarning(`Generated ${results.length} of ${modelEntries.length} model jobs before an error: ${err.message}. Do not resubmit; review the generated models.`);
            setActiveTab('generated-reports');
            return;
          }
          throw err;
        }
      }

      setGeneratedJobs(results);
      setSelectedReviewJobId(String(results[0].job_id));
      setGenerationWarning('');
      publishUnsavedChanges(false);
      setActiveTab('generated-reports');
    } catch (err) {
      setErrorMsg(err.message);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6" onChange={() => publishUnsavedChanges(true)}>
      
      {/* Title */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Initiate Pre-Dispatch Inspection (PDI)</h1>
        <p className="text-sm text-gray-500 mt-1">
          <b>Select a customer and upload the order:</b> Once both are provided, Google Gemini reads every item name, SKU, PO, and quantity, then fills the model details automatically.
        </p>
      </div>

      {errorMsg && (
        <div className="p-4 bg-red-50 border-l-4 border-red-600 rounded-r-lg flex items-start space-x-3 text-red-800 text-sm">
          <AlertTriangle className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
          <div>
            <div className="font-semibold">Notice:</div>
            <div>{errorMsg}</div>
          </div>
        </div>
      )}

      <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm space-y-3">
        <label htmlFor="pdi-customer" className="text-xs font-bold text-gray-700 uppercase tracking-wider flex items-center gap-1.5">
          <Building2 className="w-4 h-4 text-blue-700" />
          Choose OEM Customer *
        </label>
        <select
          id="pdi-customer"
          value={formData.company_name}
          onChange={event => handleSelectCustomer(event.target.value)}
          disabled={!customers.length || uploading || extracting || generating}
          className="w-full sm:max-w-md rounded-lg border border-gray-300 bg-white px-3 py-2.5 text-sm font-semibold text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
        >
          <option value="" disabled>{customers.length ? 'Select a customer' : 'Loading customers…'}</option>
          {customers.map(customer => (
            <option key={customer.name} value={customer.name}>{customerLabel(customer)}</option>
          ))}
        </select>
        {customerLoadError && <p role="alert" className="text-xs text-red-700">{customerLoadError}</p>}
      </div>

      {/* Grid: Upload Box + Template Match */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        
        {/* Upload Box (Col 1-2) */}
        <div className="md:col-span-2 bg-white p-6 rounded-xl border border-gray-200 shadow-sm space-y-4">
          <h2 className="text-base font-bold text-gray-800 flex items-center space-x-2">
            <UploadCloud className="w-5 h-5 text-blue-700" />
              <span>Upload Requirement Document (Required)</span>
          </h2>

          <div className="border-2 border-dashed border-gray-300 hover:border-blue-400 rounded-xl p-6 text-center transition cursor-pointer bg-gray-50/50">
            <input
              type="file"
              id="file-upload"
              accept=".jpg,.jpeg,.png,.pdf,.xlsx,.xls"
              onChange={handleFileChange}
              className="hidden"
            />
            <label htmlFor="file-upload" className="cursor-pointer block space-y-2">
              <div className="w-12 h-12 mx-auto rounded-full bg-blue-50 text-blue-700 flex items-center justify-center">
                <Sparkles className="w-6 h-6" />
              </div>
              <div className="text-sm font-semibold text-gray-700">
                {file ? file.name : "Choose a purchase order or requirement image/PDF"}
              </div>
              <p className="text-xs text-gray-400">
                Required. Gemini analyzes JPG/PNG images and reads text from PDF/XLSX. Extracted values populate the report below.
              </p>
            </label>
          </div>

          {(uploading || extracting) && (
            <div className="flex items-center space-x-3 text-sm text-gray-600 bg-blue-50/60 p-3 rounded-lg border border-blue-100">
              <Loader2 className="w-5 h-5 text-blue-700 animate-spin" />
              <span>
                {uploading ? "Uploading document to host..." : "Gemini is reading the document..."}
              </span>
            </div>
          )}

          {uncertainFields.length > 0 && (
            <div className="text-xs text-amber-800 bg-amber-50 p-3 rounded-lg border border-amber-200">
              Verify these difficult-to-read fields: {uncertainFields.join(', ')}. Unreadable values were left blank.
            </div>
          )}
          {file && !uploading && !extracting && !extractionFailed && (
            <div className="flex items-center space-x-2 text-xs font-semibold text-green-700 bg-green-50 p-2.5 rounded-lg border border-green-200">
              <CheckCircle2 className="w-4 h-4 shrink-0" />
              <span>
                {formData.company_name
                  ? `Document loaded: ${file.name}. Review all extracted item rows below.`
                  : `Document loaded: ${file.name}. Select a customer to extract all item names and quantities.`}
              </span>
            </div>
          )}
          {extractionFailed && formData.requirement_id && !uploading && !extracting && (
            <button type="button" onClick={handleRetryExtraction} className="px-4 py-2 text-sm font-semibold text-blue-700 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100">
              Retry image extraction
            </button>
          )}
        </div>

        {/* Template Match Card (Col 3) */}
        <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm space-y-4 flex flex-col justify-between">
          <div>
            <h2 className="text-base font-bold text-gray-800 flex items-center space-x-2">
              <Layers className="w-5 h-5 text-blue-700" />
              <span>Active Template</span>
            </h2>
            <p className="text-xs text-gray-500 mt-1">Pre-registered customer PDI format</p>

            <div className="mt-4 p-4 rounded-lg border bg-gray-50 space-y-2">
              <div className="text-xs font-medium text-gray-500">Customer OEM</div>
              <div className="font-bold text-sm text-gray-900 flex items-center justify-between">
                <span>{formData.company_name}</span>
                {templateMatch.matched && (
                  <span className="text-xs bg-green-100 text-green-800 px-2 py-0.5 rounded font-semibold">Active</span>
                )}
              </div>

              <div className="text-xs font-medium text-gray-500 pt-2 border-t">Report Template</div>
              <div className="font-semibold text-sm text-gray-900 truncate" title={templateMatch.template_name}>
                {templateMatch.template_name || 'No template selected'}
              </div>

              <div className="text-xs text-gray-500 italic">
                {templateMatch.message}
              </div>
            </div>
          </div>

          <div className="text-xs text-gray-500 bg-gray-50 p-2.5 rounded border flex items-start space-x-1.5">
            <Info className="w-4 h-4 shrink-0 mt-0.5 text-blue-600" />
            <span>Preserves the registered customer format and its inspection criteria.</span>
          </div>
        </div>

      </div>

        {file && formData.requirement_id && !uploading && !extracting && formData.company_name && (
        <div className="w-full space-y-4">
        <div className="w-full bg-white rounded-xl border border-blue-200 shadow-md overflow-hidden">
          <div className="p-5 border-b border-blue-100 bg-blue-50/60">
            <h2 className="text-base font-bold text-gray-900">
              Models for {formData.company_name || 'this customer'} ({modelEntries.length})
            </h2>
            <p className="text-xs text-gray-500 mt-1">
              Review each order line below. Every model has its own SKU, PO, lot size, and report count.
            </p>
          </div>
          <div className="p-5 space-y-4">
            {missingFields.length > 0 && (
              <p className="text-xs text-amber-800 bg-amber-50 p-3 rounded-lg border border-amber-200">
                Some order details need review. Check the model fields below and fill any blanks.
              </p>
            )}

            {!templateMatch.matched && selectableProductTypes.length > 1 && (
              <label className="block text-xs font-semibold text-gray-700">
                Product type for the report template
                <select
                  value={formData.product_type}
                  onChange={(event) => {
                    const productType = event.target.value;
                    setFormData(previous => ({ ...previous, product_type: productType }));
                    triggerMatch(formData.company_name, productType, formData.model_name);
                  }}
                  className="mt-1 w-full sm:max-w-md px-3 py-2 text-sm font-normal border rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none"
                >
                  <option value="">Select product type</option>
                  {selectableProductTypes.map(productType => (
                    <option key={productType} value={productType}>{productType}</option>
                  ))}
                </select>
              </label>
            )}

            {selectedCustomer && (
              <datalist id="pdi-customer-models">
                {selectedCustomer.models.map(model => (
                  <option key={[model.group, model.name, model.type].join('|')} value={model.name}>
                    {[model.type, model.group].filter(Boolean).join(' · ')}
                  </option>
                ))}
              </datalist>
            )}
            {modelEntries.map((model, index) => {
              const modelReportCount = getReportCount(model.lot_size, splitLot);
              return (
                <div key={model.id} className="rounded-xl border border-blue-200 bg-white shadow-sm overflow-hidden">
                  <div className="flex items-center justify-between gap-3 px-4 py-3 bg-blue-50 border-b border-blue-100">
                    <span className="text-sm font-bold text-blue-900 uppercase tracking-wide">Model {index + 1}</span>
                    {index > 0 && (
                      <button
                        type="button"
                        onClick={() => setAdditionalModels(models => models.filter(item => item.id !== model.id))}
                        className="p-2 text-red-600 hover:bg-red-50 rounded-lg"
                        aria-label={`Remove model ${index + 1}`}
                        title="Remove model"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    )}
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 p-4">
                    <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider">
                      Model name (Item Name) *
                      <input
                        type="text"
                        list={selectedCustomer ? 'pdi-customer-models' : undefined}
                        value={model.model_name}
                        onChange={(event) => updateModelEntry(index, 'model_name', event.target.value)}
                        className="mt-1.5 w-full px-3 py-3 text-sm font-semibold text-gray-900 border border-gray-300 rounded-lg shadow-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
                        placeholder="Model name"
                      />
                    </label>
                    <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider">
                      SKU *
                      <input
                        type="text"
                        value={model.product_number}
                        onChange={(event) => updateModelEntry(index, 'product_number', event.target.value)}
                        className="mt-1.5 w-full px-3 py-3 text-sm font-semibold font-mono text-gray-900 border border-gray-300 rounded-lg shadow-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
                        placeholder="SKU"
                      />
                    </label>
                    <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider">
                      Lot size *
                      <input
                        type="number"
                        min="1"
                        max="1000000"
                        value={model.lot_size}
                        onChange={(event) => updateModelEntry(index, 'lot_size', event.target.value)}
                        className="mt-1.5 w-full px-3 py-3 text-sm font-semibold text-gray-900 border border-gray-300 rounded-lg shadow-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
                      />
                      <span className="block mt-1.5 font-normal normal-case tracking-normal text-gray-500">
                        {modelReportCount} report{modelReportCount === 1 ? '' : 's'}
                      </span>
                    </label>
                    <label className="block text-xs font-bold text-gray-700 uppercase tracking-wider">
                      PO number *
                      <input
                        type="text"
                        value={model.po_number}
                        onChange={(event) => updateModelEntry(index, 'po_number', event.target.value)}
                        className="mt-1.5 w-full px-3 py-3 text-sm font-semibold text-gray-900 border border-gray-300 rounded-lg shadow-sm focus:ring-2 focus:ring-blue-500 focus:outline-none"
                        placeholder="Purchase order"
                      />
                    </label>
                  </div>
                </div>
              );
            })}

            <button
              type="button"
              onClick={() => setAdditionalModels(models => [...models, {
                id: crypto.randomUUID(),
                model_name: '',
                product_number: '',
                lot_size: '',
                po_number: formData.po_number
              }])}
              className="inline-flex items-center gap-2 px-3 py-2 text-sm font-semibold text-blue-700 bg-blue-50 hover:bg-blue-100 rounded-lg border border-blue-200"
            >
              <Plus className="w-4 h-4" />
              Add another model
            </button>

            <div className="pt-4 border-t flex justify-end">
              <button
                type="button"
                onClick={handleSubmit}
                disabled={generating || extracting || generatedJobs.length > 0 || !templateMatch.matched || !file || !formData.requirement_id}
                className={`flex items-center space-x-2 font-bold px-7 py-3 rounded-lg shadow-lg transition ${
                  generating || extracting || generatedJobs.length > 0 || !templateMatch.matched || !file || !formData.requirement_id
                    ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                    : 'bg-blue-700 hover:bg-blue-800 text-white'
                }`}
              >
                {generating ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    <span>Generating {totalReportCount} PDI {totalReportCount === 1 ? 'Report' : 'Reports'} for {formData.company_name}...</span>
                  </>
                ) : (
                  <>
                    <span>{generatedJobs.length > 0 ? 'Reports generated' : `Generate ${totalReportCount} Report${totalReportCount === 1 ? '' : 's'} for ${modelEntries.length} Model${modelEntries.length === 1 ? '' : 's'} (${formData.company_name} Format)`}</span>
                    <ArrowRight className="w-5 h-5" />
                  </>
                )}
              </button>
            </div>
          </div>
        </div>

        </div>
        )}

    </div>
  );
}
