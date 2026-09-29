import { Observable, firstValueFrom } from 'rxjs';

/** Save an in-memory `Blob` as a client-side file download. */
export function downloadBlob(blob: Blob, filename: string): void {
  const blobUrl = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = blobUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(blobUrl);
}

async function triggerBlobDownload(
  fetchBlob: () => Observable<Blob>,
  filename: string,
): Promise<void> {
  downloadBlob(await firstValueFrom(fetchBlob()), filename);
}

export async function downloadAll(
  paths: string[],
  buildUrl: (path: string) => string,
  getRaw: (url: string) => Observable<Blob>,
): Promise<void> {
  for (const path of paths) {
    const filename = path.split(/[\\/]/).pop() ?? '';
    await triggerBlobDownload(() => getRaw(buildUrl(path)), filename);
  }
}
