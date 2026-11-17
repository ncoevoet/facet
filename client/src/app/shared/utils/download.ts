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

/** Fetch one file and save it as `filename`; rejects, saving nothing, when the fetch fails. */
export async function downloadFile(blob$: Observable<Blob>, filename: string): Promise<void> {
  downloadBlob(await firstValueFrom(blob$), filename);
}
