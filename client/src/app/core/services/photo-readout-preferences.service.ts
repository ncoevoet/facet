import { Injectable, signal } from '@angular/core';

export const PHOTO_READOUT_KEY = 'facet_photo_source_readout';

/** A browser display preference; it never changes the loaded image or library. */
@Injectable({ providedIn: 'root' })
export class PhotoReadoutPreferences {
  private readonly value = signal(this.read());
  readonly visible = this.value.asReadonly();

  setVisible(visible: boolean): void {
    this.value.set(visible);
    try { localStorage.setItem(PHOTO_READOUT_KEY, String(visible)); } catch { /* session-only preference */ }
  }

  private read(): boolean {
    try { return localStorage.getItem(PHOTO_READOUT_KEY) !== 'false'; } catch { return true; }
  }
}
