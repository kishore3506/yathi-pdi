import React, { useEffect, useRef, useState } from 'react';

export default function UpdateControls() {
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const [chunkRecoveryNeeded, setChunkRecoveryNeeded] = useState(false);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [installPrompt, setInstallPrompt] = useState(null);
  const [installHelpOpen, setInstallHelpOpen] = useState(false);
  const [serviceWorkerUnavailable, setServiceWorkerUnavailable] = useState(false);
  const registrationRef = useRef(null);
  const applyingRef = useRef(false);

  useEffect(() => {
    const handleDirty = event => setHasUnsavedChanges(Boolean(event.detail));
    const handleInstallPrompt = event => {
      event.preventDefault();
      setInstallPrompt(event);
    };
    const handleControllerChange = () => {
      if (applyingRef.current) window.location.reload();
    };
    const handlePreloadError = event => {
      event.preventDefault();
      setChunkRecoveryNeeded(true);
    };

    window.addEventListener('pdi:dirty-change', handleDirty);
    window.addEventListener('beforeinstallprompt', handleInstallPrompt);
    window.addEventListener('vite:preloadError', handlePreloadError);
    navigator.serviceWorker?.addEventListener('controllerchange', handleControllerChange);

    let active = true;
    const registerServiceWorker = () => {
      if (!('serviceWorker' in navigator)) {
        setServiceWorkerUnavailable(true);
        return;
      }
      navigator.serviceWorker.register('/sw.js', { updateViaCache: 'none' })
        .then(registration => {
          if (!active || registrationRef.current) return;
          setServiceWorkerUnavailable(false);
          registrationRef.current = registration;
          if (registration.waiting && navigator.serviceWorker.controller) setUpdateAvailable(true);
          registration.addEventListener('updatefound', () => {
            const worker = registration.installing;
            if (!worker) return;
            worker.addEventListener('statechange', () => {
              if (worker.state === 'installed' && navigator.serviceWorker.controller) {
                setUpdateAvailable(true);
              }
            });
          });
          registration.update().catch(() => {});
        })
        .catch(() => {
          if (active) setServiceWorkerUnavailable(true);
        });
    };

    const checkForUpdates = () => {
      if (document.visibilityState === 'visible') registrationRef.current?.update().catch(() => {});
    };
    const handleOnline = () => {
      if (registrationRef.current) registrationRef.current.update().catch(() => {});
      else registerServiceWorker();
    };
    registerServiceWorker();
    const intervalId = window.setInterval(checkForUpdates, 5 * 60 * 1000);
    window.addEventListener('focus', checkForUpdates);
    window.addEventListener('online', handleOnline);
    document.addEventListener('visibilitychange', checkForUpdates);

    return () => {
      window.removeEventListener('pdi:dirty-change', handleDirty);
      window.removeEventListener('beforeinstallprompt', handleInstallPrompt);
      window.removeEventListener('vite:preloadError', handlePreloadError);
      navigator.serviceWorker?.removeEventListener('controllerchange', handleControllerChange);
      window.removeEventListener('focus', checkForUpdates);
      window.removeEventListener('online', handleOnline);
      document.removeEventListener('visibilitychange', checkForUpdates);
      window.clearInterval(intervalId);
      active = false;
    };
  }, []);

  const applyUpdate = () => {
    if (hasUnsavedChanges) return;
    const waitingWorker = registrationRef.current?.waiting;
    applyingRef.current = true;
    if (waitingWorker) {
      waitingWorker.postMessage({ type: 'SKIP_WAITING' });
    } else {
      window.location.reload();
    }
  };

  const install = async () => {
    if (!installPrompt) {
      setInstallHelpOpen(value => !value);
      return;
    }
    await installPrompt.prompt();
    setInstallPrompt(null);
  };

  return (
    <div className="fixed inset-x-0 top-0 z-[70] flex flex-col items-center gap-2 px-3 pt-2">
      {(updateAvailable || chunkRecoveryNeeded) && (
        <div role="status" className="flex w-full max-w-3xl flex-col gap-3 rounded-xl border border-blue-200 bg-white p-3 shadow-lg sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm font-semibold text-blue-950">
            {chunkRecoveryNeeded
              ? 'A newer app version is required. Save your work and reload.'
              : 'Update available. Save your work and reload.'}
          </p>
          <button
            type="button"
            onClick={applyUpdate}
            disabled={hasUnsavedChanges}
            className="min-h-10 shrink-0 rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            {hasUnsavedChanges ? 'Save work before updating' : 'Reload to update'}
          </button>
        </div>
      )}
      {serviceWorkerUnavailable && (
        <p role="status" className="rounded-lg border bg-white px-3 py-2 text-xs text-slate-700 shadow">
          App updates are unavailable. Reconnect and reload this page.
        </p>
      )}
      <div className="self-end">
        <button type="button" onClick={install} className="min-h-10 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm">
          Install app
        </button>
        {installHelpOpen && (
          <div className="mt-2 max-w-xs rounded-xl border bg-white p-3 text-xs leading-5 text-slate-700 shadow-lg">
            <strong>Install this PWA</strong>
            <p className="mt-1">Android Chrome: open the browser menu and choose “Install app” or “Add to Home screen”. Windows Chrome or Edge: use the install icon in the address bar, or choose the browser’s “Install this site as an app” menu option.</p>
            <p className="mt-2">Menu wording varies by browser. Keep the device online to use reports and receive updates.</p>
          </div>
        )}
      </div>
    </div>
  );
}
