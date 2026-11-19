import React, { useEffect, useRef, useState } from 'react';
import { Camera, X } from 'lucide-react';

const cameraErrorMessage = (error) => {
  switch (error.name) {
    case 'NotAllowedError':
    case 'SecurityError':
      if (/denied by system|os permission/i.test(error.message)) {
        return navigator.userAgent.includes('Windows')
          ? 'Windows blocked camera access. In Settings → Privacy & security → Camera, turn on Camera access and Let desktop apps access your camera. Then select Retry camera.'
          : 'Your device blocked the camera. Allow camera access for your browser in your device settings, then retry.';
      }
      return 'Camera permission is blocked for this site. In your browser’s site settings, set Camera to Allow, then retry.';
    case 'NotFoundError':
    case 'OverconstrainedError':
      return 'No usable camera was found. Connect or enable a webcam, then retry.';
    case 'NotReadableError':
    case 'AbortError':
      return 'The camera could not start. Close other apps using it and check the webcam’s privacy switch, then retry.';
    default:
      return 'The camera could not start. Retry the camera or use Upload images in the email dialog.';
  }
};

export default function ScanCameraDialog({ onCapture, onClose }) {
  const dialog = useRef(null);
  const video = useRef(null);
  const active = useRef(false);
  const [ready, setReady] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [previewBlocked, setPreviewBlocked] = useState(false);

  useEffect(() => {
    const cameraDialog = dialog.current;
    active.current = true;
    cameraDialog.showModal();
    return () => {
      active.current = false;
      cameraDialog.close();
    };
  }, []);

  useEffect(() => {
    const preview = video.current;
    let cancelled = false;
    let stream;
    const start = async () => {
      if (!window.isSecureContext) {
        setError('Open PDI using its localhost or HTTPS address to use the camera.');
        return;
      }
      if (!navigator.mediaDevices?.getUserMedia) {
        setError('This browser does not expose a camera. Open PDI in Chrome or Edge to scan.');
        return;
      }
      try {
        try {
          stream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: { ideal: 'environment' }, width: { ideal: 2400 } },
            audio: false,
          });
        } catch (err) {
          if (cancelled) return;
          if (!['OverconstrainedError', 'NotFoundError', 'NotReadableError', 'AbortError'].includes(err.name)) throw err;
          stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        }
        if (cancelled) {
          stream.getTracks().forEach(track => track.stop());
          return;
        }
      } catch (err) {
        if (!cancelled) setError(cameraErrorMessage(err));
        return;
      }
      preview.srcObject = stream;
      try {
        await preview.play();
      } catch {
        if (!cancelled) setPreviewBlocked(true);
      }
    };
    start();
    return () => {
      cancelled = true;
      stream?.getTracks().forEach(track => track.stop());
      preview.srcObject = null;
    };
  }, [attempt]);

  const retry = () => {
    setReady(false);
    setCapturing(false);
    setPreviewBlocked(false);
    setError('');
    setAttempt(current => current + 1);
  };

  const startPreview = async () => {
    try {
      await video.current.play();
    } catch {
      setPreviewBlocked(false);
      setError('The camera preview could not start. Retry the camera or use Upload images.');
    }
  };

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
      <video ref={video} muted autoPlay playsInline hidden={!!error || previewBlocked} onPlaying={() => {
        setReady(true);
        setPreviewBlocked(false);
      }}
        className="mt-2 max-h-[65vh] w-full rounded bg-black object-contain" />
      {error || previewBlocked ? (
        <div className="mt-2 space-y-3">
          <p className="text-sm text-red-700" role="alert">{error || 'The camera opened, but the browser paused the preview.'}</p>
          <button type="button" onClick={previewBlocked ? startPreview : retry}
            className="rounded-lg border border-blue-200 px-3 py-2 text-sm font-semibold text-blue-800">
            {previewBlocked ? 'Start preview' : 'Retry camera'}
          </button>
        </div>
      ) : (
        <button type="button" onClick={capture} disabled={!ready || capturing}
          className="mt-3 inline-flex items-center gap-2 rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">
          <Camera className="h-4 w-4" /> {capturing ? 'Capturing…' : ready ? 'Capture scan' : 'Opening camera…'}
        </button>
      )}
    </dialog>
  );
}
