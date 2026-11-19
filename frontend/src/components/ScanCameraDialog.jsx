import React, { useEffect, useRef, useState } from 'react';
import { Camera, X } from 'lucide-react';
import { scanJpeg } from '../services/scanImages';

const hasPhoneCameraPicker = () => navigator.userAgentData?.mobile ||
  /Android|iPhone|iPad|iPod/i.test(navigator.userAgent) ||
  (navigator.userAgent.includes('Macintosh') && navigator.maxTouchPoints > 1);

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
  const phoneCameraPicker = hasPhoneCameraPicker();
  const [livePreview, setLivePreview] = useState(!phoneCameraPicker);

  useEffect(() => {
    const cameraDialog = dialog.current;
    active.current = true;
    if (cameraDialog.showModal) cameraDialog.showModal();
    else cameraDialog.setAttribute('open', '');
    return () => {
      active.current = false;
      if (cameraDialog.close) cameraDialog.close();
      else cameraDialog.removeAttribute('open');
    };
  }, []);

  useEffect(() => {
    if (!livePreview) return;
    const preview = video.current;
    let cancelled = false;
    let stream;
    const start = async () => {
      if (!window.isSecureContext) {
        setError('Live preview needs an HTTPS PDI address on a phone, or localhost on the computer running PDI.');
        return;
      }
      if (!navigator.mediaDevices?.getUserMedia) {
        setError('Live preview is unavailable in this browser. Use your phone camera or open PDI in a browser with camera access.');
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
  }, [attempt, livePreview]);

  const retry = () => {
    setReady(false);
    setCapturing(false);
    setPreviewBlocked(false);
    setError('');
    setAttempt(current => current + 1);
  };

  const switchCaptureMode = () => {
    retry();
    setLivePreview(current => !current);
  };

  const startPreview = async () => {
    try {
      await video.current.play();
    } catch {
      setPreviewBlocked(false);
      setError('The camera preview could not start. Retry the camera or use Upload images.');
    }
  };

  const capture = async () => {
    const preview = video.current;
    if (!preview.videoWidth || !preview.videoHeight) return;
    setCapturing(true);
    try {
      const image = await scanJpeg(preview, preview.videoWidth, preview.videoHeight);
      if (active.current) onCapture(image);
    } catch {
      if (active.current) {
        setCapturing(false);
        setError('The image could not be captured. Try using Upload images.');
      }
    }
  };

  return (
    <dialog ref={dialog} aria-labelledby="email-scan-camera-title"
      onCancel={event => { event.preventDefault(); onClose(); }}
      className="fixed inset-0 z-[60] m-auto w-[calc(100%-2rem)] max-w-xl rounded-xl bg-white p-4 shadow-xl backdrop:bg-black/60">
      <div className="flex items-center justify-between gap-3">
        <h2 id="email-scan-camera-title" className="font-bold text-gray-900">Scan with camera</h2>
        <button type="button" onClick={onClose} aria-label="Close camera" className="rounded p-2 hover:bg-gray-100">
          <X className="h-5 w-5" />
        </button>
      </div>
      {!livePreview && (
        <label className="mt-3 inline-flex cursor-pointer items-center gap-2 rounded-lg bg-blue-700 px-3 py-2 text-sm font-semibold text-white focus-within:ring-2 focus-within:ring-blue-600">
          <Camera className="h-4 w-4" /> Take photo
          <input type="file" accept="image/*" capture="environment" className="sr-only"
            onChange={event => {
              const image = event.currentTarget.files[0];
              event.currentTarget.value = '';
              if (image) onCapture(image);
            }} />
        </label>
      )}
      <video ref={video} muted autoPlay playsInline hidden={!livePreview || !!error} onPlaying={() => {
        setReady(true);
        setPreviewBlocked(false);
      }}
        className="mt-2 max-h-[65vh] w-full rounded bg-black object-contain" />
      {livePreview && (error || previewBlocked ? (
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
      ))}
      {phoneCameraPicker && (
        <button type="button" onClick={switchCaptureMode} disabled={capturing}
          className="ml-2 mt-3 rounded-lg border border-gray-300 px-3 py-2 text-sm font-semibold text-gray-700 disabled:opacity-50">
          {livePreview ? 'Use phone camera' : 'Use live preview'}
        </button>
      )}
    </dialog>
  );
}
