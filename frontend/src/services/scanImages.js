const MAX_SCAN_EDGE = 2400;
const MAX_UPLOAD_BYTES = 8 * 1024 * 1024;
const SERVER_IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);

export function scanJpeg(source, width, height) {
  const canvas = document.createElement('canvas');
  const scale = Math.min(1, MAX_SCAN_EDGE / Math.max(width, height));
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));
  canvas.getContext('2d').drawImage(source, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) => {
    canvas.toBlob(image => {
      if (image) resolve(image);
      else reject(new Error('The image could not be saved. Try taking it again.'));
    }, 'image/jpeg', 0.9);
  });
}

export async function prepareScanImage(file) {
  if (file.size <= MAX_UPLOAD_BYTES && (
    SERVER_IMAGE_TYPES.has(file.type) || (!file.type && /\.(jpe?g|png|webp)$/i.test(file.name))
  )) return file;

  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = reject;
      image.src = url;
    });
    return await scanJpeg(image, image.naturalWidth, image.naturalHeight);
  } catch {
    throw new Error('This browser could not open that image. Retake it using the live preview or choose a JPG, PNG, or WebP image.');
  } finally {
    URL.revokeObjectURL(url);
  }
}
