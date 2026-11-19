import React, { useEffect, useRef, useState } from 'react';
import { Camera, ImagePlus, X } from 'lucide-react';
import { api } from '../services/api';
import './stg-format.css';

const PHOTO_TYPES = 'image/jpeg,image/png,image/webp';

export default function StgPhotoSlots({ report, modelInput, disabled, onSave }) {
  const [error, setError] = useState('');
  const [cameraSlot, setCameraSlot] = useState(null);
  const [cameraError, setCameraError] = useState('');
  const [cameraReady, setCameraReady] = useState(false);
  const dialog = useRef(null);
  const video = useRef(null);
  const stream = useRef(null);
  const cameraRequest = useRef(0);

  useEffect(() => () => {
    cameraRequest.current += 1;
    stream.current?.getTracks().forEach(track => track.stop());
  }, []);

  const savePhoto = async (slot, file) => {
    setError('');
    if (file?.size > 8 * 1024 * 1024) {
      setError(`${slot.label}: Choose a photo of 8 MB or less.`);
      return;
    }
    try {
      await onSave(slot.key, file);
    } catch (err) {
      setError(`${slot.label}: ${err.message}`);
    }
  };

  const closeCamera = () => {
    cameraRequest.current += 1;
    stream.current?.getTracks().forEach(track => track.stop());
    stream.current = null;
    if (video.current) video.current.srcObject = null;
    dialog.current?.close();
    setCameraSlot(null);
    setCameraReady(false);
  };

  const openCamera = async (slot) => {
    const request = ++cameraRequest.current;
    setError('');
    setCameraError('');
    setCameraReady(false);
    setCameraSlot(slot);
    dialog.current.showModal();
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraError('Live preview requires HTTPS or localhost and a camera-enabled browser.');
      return;
    }
    try {
      const media = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1400 } },
        audio: false,
      });
      if (request !== cameraRequest.current) {
        media.getTracks().forEach(track => track.stop());
        return;
      }
      stream.current = media;
      video.current.srcObject = media;
      await video.current.play();
    } catch (err) {
      if (request !== cameraRequest.current) return;
      stream.current?.getTracks().forEach(track => track.stop());
      stream.current = null;
      setCameraReady(false);
      setCameraError(err.name === 'NotAllowedError'
        ? 'Camera access was denied. Allow camera access in your browser or upload a photo.'
        : 'The camera is unavailable. Try the device camera option or upload a photo.');
    }
  };

  const capture = () => {
    const preview = video.current;
    if (!cameraSlot || !preview?.videoWidth || !preview.videoHeight) return;
    const slot = cameraSlot;
    const canvas = document.createElement('canvas');
    const scale = Math.min(1, 1400 / Math.max(preview.videoWidth, preview.videoHeight));
    canvas.width = Math.round(preview.videoWidth * scale);
    canvas.height = Math.round(preview.videoHeight * scale);
    canvas.getContext('2d').drawImage(preview, 0, 0, canvas.width, canvas.height);
    closeCamera();
    canvas.toBlob(photo => {
      if (photo) savePhoto(slot, photo);
      else setError(`${slot.label}: The photo could not be captured.`);
    }, 'image/jpeg', 0.9);
  };

  const photoCell = slot => (
    <td key={slot.key} className="stg-photo-cell">
    {slot.has_photo ? (
      <img
        alt={slot.label}
        src={api.getReportPhotoUrl(report.id, slot.key, report.revision)}
        className="h-32 w-full object-contain sm:h-40"
        loading="lazy"
      />
    ) : (
      <div className="h-28 sm:h-36" />
    )}
    {(!['Approved', 'Emailed'].includes(report.status)) && (
      <div className="flex flex-wrap justify-center gap-1">
        <label className="inline-flex min-h-9 cursor-pointer items-center gap-1.5 rounded border border-gray-300 px-2.5 py-1.5 text-xs font-semibold focus-within:ring-2 focus-within:ring-blue-500">
          <ImagePlus className="h-4 w-4" aria-hidden="true" /> Upload
          <input
            type="file" accept={PHOTO_TYPES} className="sr-only" aria-label={`Upload ${slot.label}`}
            disabled={disabled}
            onChange={event => {
              event.stopPropagation();
                  const file = event.target.files[0];
              event.target.value = '';
              if (file) savePhoto(slot, file);
            }}
          />
        </label>
        <button
          type="button" onClick={() => openCamera(slot)} disabled={disabled}
          aria-label={`Open camera for ${slot.label}`}
          className="inline-flex min-h-9 items-center gap-1.5 rounded border border-blue-200 bg-blue-50 px-2.5 py-1.5 text-xs font-semibold text-blue-800 disabled:opacity-50"
        >
          <Camera className="h-4 w-4" aria-hidden="true" /> Camera
        </button>
        {slot.has_photo && (
          <button
            type="button" onClick={() => savePhoto(slot, null)} disabled={disabled}
            aria-label={`Remove ${slot.label}`}
            className="min-h-9 px-1 text-xs font-semibold text-red-700 disabled:opacity-50"
          >Remove</button>
        )}
      </div>
    )}
    </td>
  );

  const groups = report.report_data.photo_groups;
  const sectionTitles = [
    'Section 1 → Product Photos',
    'Section 2 → Sticker / Label Photos',
    'Section 3 → Inner Box Photo',
    'Section 4 → Outer Carton Photo',
  ];

  const photoRows = (slots, labels) => (
    <>
      <tr className="stg-photo-label">{slots.map((slot, index) => <th key={slot.key}>{labels?.[index] || slot.label}</th>)}</tr>
      <tr>{slots.map(photoCell)}</tr>
    </>
  );

  const packagingRows = (slots, isCarton) => {
    const heading = isCarton ? 'Carton Dimensions' : 'Box Dimensions';
    const quantity = isCarton ? 'No. of Boxes/Bags in a carton' : 'No. of Pieces in a box/Bag';
    return (
      <>
        <tr className="stg-photo-label">
          {slots.map(slot => <th key={slot.key}>{slot.label}</th>)}<th>{heading}</th>
        </tr>
        <tr>
          {slots.map(photoCell)}
          <td><dl className="stg-packaging-dimensions">{['Length', 'Width', 'Height', 'No. of Ply', quantity].map(label => (
            <div key={label}><dt>{label}</dt><dd /></div>
          ))}</dl></td>
        </tr>
      </>
    );
  };

  return (
    <section aria-labelledby="stg-photos-heading" className="mt-4 overflow-x-auto">
      <h2 id="stg-photos-heading" className="sr-only">Inspection Photos</h2>
      {error && <p role="alert" className="mb-3 rounded bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}
      <table className="stg-format-table stg-photo-table">
        <tbody>
          {groups.slice(0, 4).map((group, index) => (
            <React.Fragment key={group.label}>
              <tr className="stg-section-title"><th colSpan={3}>{sectionTitles[index]}</th></tr>
              {index === 0 && (
                <>
                  <tr><th>Item 1 Name:</th><td colSpan={2}>{modelInput}</td></tr>
                  <tr><th>Brand:</th><td colSpan={2} className="text-center">STG</td></tr>
                </>
              )}
              {photoRows(group.slots.slice(0, 3))}
              {index < 2 ? photoRows(group.slots.slice(3)) : packagingRows(group.slots.slice(3), index === 3)}
            </React.Fragment>
          ))}
        </tbody>
      </table>
      <table className="stg-format-table stg-photo-table mt-5">
        <tbody>
          {groups.slice(4).map((group, index) => (
            <React.Fragment key={group.label}>
              {(index === 0 || index === 2) && (
                <tr className="stg-section-title"><th colSpan={3}>
                  {index === 0 ? 'Section 5 → Dimensional Measurement Photos' : 'Section 5 continues → Dimensional measurement Photos'}
                </th></tr>
              )}
              <tr className="stg-section-title"><th>Size</th><td colSpan={2}><span className="sr-only">Measurement group {index + 1}</span></td></tr>
              {photoRows(group.slots.slice(0, 3), ['Length:', 'Width:', 'Height:'])}
              {photoRows(group.slots.slice(3), ['Other Specification 1 (If any):', 'Other Specification 2 (If any):', 'Weight:'])}
            </React.Fragment>
          ))}
        </tbody>
      </table>
      <dialog
        ref={dialog} aria-labelledby="stg-camera-title"
        onCancel={event => { event.preventDefault(); closeCamera(); }}
        className="m-auto w-[calc(100%-2rem)] max-w-xl rounded-xl bg-white p-4 shadow-xl backdrop:bg-black/60 sm:p-5"
      >
        <div className="flex items-center justify-between gap-3">
          <h2 id="stg-camera-title" className="font-bold text-gray-900">{cameraSlot?.label}</h2>
          <button type="button" onClick={closeCamera} aria-label="Close camera" className="rounded p-2 hover:bg-gray-100">
            <X className="h-5 w-5" />
          </button>
        </div>
        <video
          ref={video} autoPlay playsInline muted hidden={!!cameraError}
          onPlaying={() => setCameraReady(true)}
          className="mt-3 max-h-[55vh] w-full rounded bg-black object-contain"
        />
        {cameraError ? (
          <div className="mt-3 space-y-3">
            <p role="alert" className="text-sm text-gray-700">{cameraError}</p>
            <label className="inline-flex cursor-pointer items-center rounded bg-blue-700 px-3 py-2 text-sm font-semibold text-white focus-within:ring-2 focus-within:ring-blue-500">
              Try device camera
              <input
                type="file" accept="image/*" capture="environment" className="sr-only"
                onChange={event => {
                  event.stopPropagation();
                  const file = event.target.files[0];
                  event.target.value = '';
                  const slot = cameraSlot;
                  closeCamera();
                  if (file && slot) savePhoto(slot, file);
                }}
              />
            </label>
          </div>
        ) : (
          <button
            type="button" onClick={capture} disabled={!cameraReady || disabled}
            className="mt-3 inline-flex min-h-10 items-center gap-2 rounded bg-blue-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            <Camera className="h-4 w-4" aria-hidden="true" /> {cameraReady ? 'Capture photo' : 'Opening camera…'}
          </button>
        )}
      </dialog>
    </section>
  );
}
