import React, { useEffect, useRef, useState } from 'react';
import { Camera, X } from 'lucide-react';

export default function ScanCameraDialog({ onCapture, onClose }) {
  const dialog = useRef(null);
  const video = useRef(null);
  const active = useRef(false);
  const [ready, setReady] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const cameraDialog = dialog.current;
    let cancelled = false;
    let stream;
    active.current = true;
    cameraDialog.showModal();
    const start = async () => {
      try {
        stream = await navigator.mediaDevices?.getUserMedia({
          video: { facingMode: { ideal: 'environment' }, width: { ideal: 2400 } },
          audio: false,
        });
        if (cancelled) {
          stream?.getTracks().forEach(track => track.stop());
          return;
        }
        if (!stream) throw new Error();
        video.current.srcObject = stream;
        await video.current.play();
      } catch {
        if (!cancelled) {
          stream?.getTracks().forEach(track => track.stop());
          setError('Camera unavailable. Allow camera access in your browser or use Upload images.');
        }
      }
    };
    start();
    return () => {
      cancelled = true;
      active.current = false;
      stream?.getTracks().forEach(track => track.stop());
      cameraDialog.close();
    };
  }, []);

  const capture = () => {
    const preview = video.current;
    if (!preview.videoWidth || !preview.videoHeight) return;
    const canvas = document.createElement('canvas');
    const scale = Math.min(1, 2400 / Math.max(preview.videoWidth, preview.videoHeight));
    canvas.width = Math.round(preview.videoWidth * scale);
    canvas.height = Math.round(preview.videoHeight * scale);
    canvas.getContext('2d').drawImage(preview, 0, 0, canvas.width, canvas.height);
    setCapturing(true);
    canvas.toBlob(image => {
      if (!active.current) return;
      if (image) onCapture(image);
      else {
        setCapturing(false);
        setError('The image could not be captured. Try using Upload images.');
      }
    }, 'image/jpeg', 0.9);
  };

  return (
    <dialog ref={dialog} aria-labelledby="email-scan-camera-title"
      onCancel={event => { event.preventDefault(); onClose(); }}
      className="m-auto w-[calc(100%-2rem)] max-w-xl rounded-xl bg-white p-4 shadow-xl backdrop:bg-black/60">
      <div className="flex items-center justify-between gap-3">
        <h2 id="email-scan-camera-title" className="font-bold text-gray-900">Scan with camera</h2>
        <button type="button" onClick={onClose} aria-label="Close camera" className="rounded p-2 hover:bg-gray-100">
          <X className="h-5 w-5" />
        </button>
      </div>
      <video ref={video} muted autoPlay playsInline hidden={!!error} onPlaying={() => setReady(true)}
        className="mt-2 max-h-[65vh] w-full rounded bg-black object-contain" />
      {error ? <p className="mt-2 text-sm text-red-700" role="alert">{error}</p> : (
        <button type="button" onClick={capture} disabled={!ready || capturing}
          className="mt-3 inline-flex items-center gap-2 rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">
          <Camera className="h-4 w-4" /> {capturing ? 'Capturing…' : ready ? 'Capture scan' : 'Opening camera…'}
        </button>
      )}
    </dialog>
  );
}
