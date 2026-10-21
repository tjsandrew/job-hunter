// Cloud downloads navigate directly to the signed URL. Fetching through an API
// redirect changes the cross-origin request and can fail S3 CORS validation.
export function downloadFile(file: Blob | {url: string}, filename: string) {
  const local = file instanceof Blob;
  const url = local ? URL.createObjectURL(file) : file.url;
  if (!local && new URL(url).protocol !== 'https:') throw new Error('Invalid download address.');
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = 'noreferrer';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  if (local) window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
