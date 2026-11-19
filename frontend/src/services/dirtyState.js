export const publishUnsavedChanges = (hasUnsavedChanges) => {
  window.dispatchEvent(new CustomEvent('pdi:dirty-change', { detail: hasUnsavedChanges }));
};
