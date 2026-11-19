import React, { useEffect, useState } from 'react';
import { AlertCircle, Loader2, ShieldCheck } from 'lucide-react';

const EMPTY_IMAGES = {
  carton_with_label: null,
  product_name_plate: null,
  technical_specs: null,
};

const IMAGE_FIELDS = [
  { key: 'carton_with_label', label: 'Carton with Label' },
  { key: 'product_name_plate', label: 'Product Name Plate / Labels/Engraving' },
  { key: 'technical_specs', label: 'Technical Specs Details' },
];

const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

export default function LegalChecklistReview({ job, checklist, onAgree }) {
  const [items, setItems] = useState(checklist?.items || []);
  const [mrpValue, setMrpValue] = useState(checklist?.mrp_value || '');
  const [images, setImages] = useState({ ...EMPTY_IMAGES, ...checklist?.images });
  const [agreed, setAgreed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [pendingImageReads, setPendingImageReads] = useState(0);
  const [error, setError] = useState('');

  useEffect(() => {
    setItems(checklist?.items || []);
    setMrpValue(checklist?.mrp_value || '');
    setImages({ ...EMPTY_IMAGES, ...checklist?.images });
    setAgreed(false);
    setError('');
  }, [checklist, job?.id]);

  const allChecksReviewed = items.length > 0 && items.every(
    item => item.is_mrp || item.status === 'OK' || item.status === 'NG'
  );
  const canAgree = allChecksReviewed && mrpValue.trim() && agreed && !saving && pendingImageReads === 0;

  const updateItem = (rowIndex, updates) => {
    setItems(current => current.map(item => (
      item.row_index === rowIndex ? { ...item, ...updates } : item
    )));
  };

  const readImageFile = (field, file) => {
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      setError('Choose or paste a valid image file.');
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setError('Each image must be smaller than 5 MB.');
      return;
    }

    const reader = new FileReader();
    setPendingImageReads(count => count + 1);
    reader.onload = () => {
      setPendingImageReads(count => Math.max(0, count - 1));
      if (typeof reader.result !== 'string') {
        setError('The selected image could not be read.');
        return;
      }
      setImages(current => ({ ...current, [field]: reader.result }));
      setError('');
    };
    reader.onerror = () => {
      setPendingImageReads(count => Math.max(0, count - 1));
      setError('The selected image could not be read.');
    };
    reader.readAsDataURL(file);
  };

  const handleImagePaste = (field, event) => {
    const imageItem = Array.from(event.clipboardData?.items || [])
      .find(item => item.type.startsWith('image/'));
    if (!imageItem) return;
    event.preventDefault();
    readImageFile(field, imageItem.getAsFile());
  };

  const handleAgree = async () => {
    if (!canAgree) return;
    setSaving(true);
    setError('');
    try {
      await onAgree({
        agreed: true,
        mrp_value: mrpValue.trim(),
        items: items.map(item => ({
          row_index: item.row_index,
          status: item.is_mrp ? null : item.status,
        })),
        images,
      });
    } catch (err) {
      setError(err.message || 'Could not save the legal checklist.');
    } finally {
      setSaving(false);
    }
  };

  if (!checklist?.items?.length) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-800">
        The J1 legal checklist is unavailable for this model. It cannot be agreed or emailed until it is restored.
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="rounded-xl bg-gradient-to-r from-blue-800 to-indigo-900 p-6 text-white shadow">
        <p className="text-xs font-bold uppercase tracking-wider text-blue-200">Havells Legal Review</p>
        <h1 className="mt-1 text-2xl font-bold">J1 Legal Compliance Checksheet</h1>
        <p className="mt-2 text-sm text-blue-100">
          Review and complete this model&apos;s checksheet after approving its PDI reports.
        </p>
      </div>

      <div className="grid gap-3 rounded-xl border bg-white p-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <div><span className="text-xs text-gray-500">Model</span><p className="font-semibold">{job.model_name || job.product_type || '—'}</p></div>
        <div><span className="text-xs text-gray-500">SKU</span><p className="font-semibold">{job.product_number || '—'}</p></div>
        <div><span className="text-xs text-gray-500">PO Number</span><p className="font-semibold">{job.po_number || '—'}</p></div>
        <div><span className="text-xs text-gray-500">Lot Quantity</span><p className="font-semibold">{job.lot_size || '—'}</p></div>
      </div>

      <div className="overflow-hidden rounded-xl border bg-white shadow-sm">
        <div className="overflow-x-auto">
          <table className="min-w-[1100px] w-full border-collapse text-left text-xs">
            <thead className="bg-gray-800 text-white">
              <tr>
                <th className="border p-2">S.N.</th>
                <th className="border p-2">Key Check Item</th>
                <th className="border p-2">Key Checkpoint Details</th>
                <th className="border p-2">Method</th>
                <th className="border p-2">OK / NG or MRP</th>
                <th className="border p-2">Remarks</th>
              </tr>
            </thead>
            <tbody>
              {items.map(item => (
                <tr key={item.row_index} className="align-top even:bg-gray-50">
                  <td className="border p-2 font-semibold">{item.number}</td>
                  <td className="border p-2">{item.category}</td>
                  <td className="whitespace-pre-line border p-2">{item.details}</td>
                  <td className="border p-2">{item.method}</td>
                  <td className="border p-2">
                    {item.is_mrp ? (
                      <input
                        type="text"
                        value={mrpValue}
                        onChange={event => setMrpValue(event.target.value)}
                        aria-label="Model-specific MRP value"
                        placeholder="Enter this model's MRP"
                        className="w-36 rounded border px-2 py-1"
                      />
                    ) : (
                      <select
                        value={item.status || ''}
                        onChange={event => updateItem(item.row_index, { status: event.target.value || null })}
                        aria-label={`Checklist item ${item.number} status`}
                        className="w-24 rounded border bg-white px-2 py-1"
                      >
                        <option value="">Select</option>
                        <option value="OK">OK</option>
                        <option value="NG">NG</option>
                      </select>
                    )}
                  </td>
                  <td className="border p-2">
                    <span aria-label={`Checklist item ${item.number} remarks`}>-</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <section className="space-y-3 border-t p-4" aria-label="Product evidence pictures">
          <div>
            <h2 className="text-sm font-bold text-gray-900">Product evidence pictures</h2>
            <p className="mt-1 text-xs text-gray-600">
              Click a box and press Ctrl+V to paste a picture, or choose an image file.
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            {IMAGE_FIELDS.map(({ key, label }) => (
              <div
                key={key}
                role="group"
                aria-label={label}
                tabIndex={0}
                onPaste={event => handleImagePaste(key, event)}
                onDragOver={event => event.preventDefault()}
                onDrop={event => {
                  event.preventDefault();
                  readImageFile(key, event.dataTransfer.files?.[0]);
                }}
                className="flex min-h-48 flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-gray-300 bg-gray-50 p-3 text-center outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
              >
                <p className="text-xs font-semibold text-gray-800">{label}</p>
                {images[key] ? (
                  <img
                    src={images[key]}
                    alt={`${label} evidence`}
                    className="max-h-32 max-w-full object-contain"
                  />
                ) : (
                  <p className="text-xs text-gray-500">Paste an image here</p>
                )}
                <label className="cursor-pointer rounded border bg-white px-2 py-1 text-xs font-medium text-gray-700 hover:bg-gray-100">
                  Choose image
                  <input
                    type="file"
                    accept="image/*"
                    className="sr-only"
                    onChange={event => {
                      readImageFile(key, event.target.files?.[0]);
                      event.target.value = '';
                    }}
                  />
                </label>
                {images[key] && (
                  <button
                    type="button"
                    onClick={() => setImages(current => ({ ...current, [key]: null }))}
                    className="text-xs font-medium text-red-700 hover:text-red-900"
                  >
                    Remove image
                  </button>
                )}
              </div>
            ))}
          </div>
        </section>

        <div className="space-y-4 border-t bg-gray-50 p-4">
          {error && (
            <div className="flex items-center gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-700">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}
          <label className="flex items-start gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={agreed}
              onChange={event => setAgreed(event.target.checked)}
              className="mt-0.5"
            />
            <span>I have reviewed this J1 legal checksheet and agree with the recorded values.</span>
          </label>
          <div className="flex justify-end">
            <button
              type="button"
              onClick={handleAgree}
              disabled={!canAgree}
              className="flex items-center gap-2 rounded-lg bg-green-700 px-5 py-2.5 text-sm font-bold text-white shadow hover:bg-green-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
              <span>{saving ? 'Saving legal checksheet...' : 'Agree & Continue'}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
