import { Injectable, signal } from '@angular/core';

/** A presentation preference, never a photo filter or a server query parameter. */
@Injectable({ providedIn: 'root' })
export class FaceOutlinePreferences {
  readonly enabled = signal(this.read());
  setEnabled(enabled: boolean): void {
    this.enabled.set(enabled);
    try { localStorage.setItem('facet_face_outlines', String(enabled)); } catch { /* browser storage unavailable */ }
  }
  private read(): boolean {
    try { return localStorage.getItem('facet_face_outlines') !== 'false'; } catch { return true; }
  }
}
