import { TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { By } from '@angular/platform-browser';
import { vi } from 'vitest';
import { CompareSelectedDialogComponent } from './compare-selected-dialog.component';
import { FIT_ZOOM, MAX_COMPARE_PANES, SyncedZoomComponent } from './synced-zoom.component';
import { Photo } from '../../shared/models/photo.model';
import { I18nService } from '../../core/services/i18n.service';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';

const photo = (path: string): Photo => ({ path, filename: path.slice(1) } as Photo);

function build(paths: string[]) {
  const dialogRef = { close: vi.fn() };
  TestBed.configureTestingModule({
    imports: [CompareSelectedDialogComponent],
    providers: [
      { provide: MAT_DIALOG_DATA, useValue: { photos: paths.map(photo) } },
      { provide: MatDialogRef, useValue: dialogRef },
      { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}) } },
    ],
  });
  const fixture = TestBed.createComponent(CompareSelectedDialogComponent);
  fixture.detectChanges();
  return { fixture, dialogRef };
}

describe('CompareSelectedDialogComponent', () => {
  afterEach(() => TestBed.resetTestingModule());

  it('renders one synced pane per selected photo', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg']);
    const panes = fixture.debugElement.nativeElement.querySelectorAll('app-synced-zoom');
    expect(panes.length).toBe(2);
  });

  it('renders a 2x2 grid for four photos', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg']);
    expect(fixture.debugElement.nativeElement.querySelectorAll('app-synced-zoom').length).toBe(4);
  });

  it('drops photos beyond the pane cap rather than shrinking them all', () => {
    const paths = Array.from({ length: MAX_COMPARE_PANES + 3 }, (_, i) => `/p${i}.jpg`);
    const { fixture } = build(paths);
    expect(fixture.debugElement.nativeElement.querySelectorAll('app-synced-zoom').length)
      .toBe(MAX_COMPARE_PANES);
  });

  it('gives each pane its own stored thumbnail as placeholder, keyed by its frame', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg']);
    const urls = new ThumbnailUrlPipe();
    const panes = fixture.debugElement.queryAll(By.directive(SyncedZoomComponent))
      .map(de => de.componentInstance as SyncedZoomComponent);
    expect(panes.map(p => p.placeholderSrc())).toEqual([urls.transform('/a.jpg', 640), urls.transform('/b.jpg', 640)]);
    expect(panes.map(p => p.frameKey())).toEqual(['/a.jpg', '/b.jpg']);
  });

  it('a zoom from one pane drives every other pane', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg']);
    const panes = fixture.debugElement.queryAll(
      (de) => de.componentInstance instanceof SyncedZoomComponent,
    );
    const next = { scale: 3, tx: 12, ty: -8 };
    panes[0].componentInstance.zoomChange.emit(next);
    fixture.detectChanges();
    expect(panes[0].componentInstance.zoom()).toEqual(next);
    expect(panes[1].componentInstance.zoom()).toEqual(next);
  });

  it('starts fitted and offers the reset only once zoomed', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg']);
    const resetSelector = 'button[aria-label="gallery.compare.reset_zoom"]';
    expect(fixture.debugElement.nativeElement.querySelector(resetSelector)).toBeNull();

    const pane = fixture.debugElement.query(
      (de) => de.componentInstance instanceof SyncedZoomComponent,
    );
    pane.componentInstance.zoomChange.emit({ scale: 2, tx: 0, ty: 0 });
    fixture.detectChanges();
    expect(fixture.debugElement.nativeElement.querySelector(resetSelector)).not.toBeNull();

    fixture.debugElement.nativeElement.querySelector(resetSelector).click();
    fixture.detectChanges();
    expect(pane.componentInstance.zoom()).toEqual(FIT_ZOOM);
  });

  it('closes through the dialog ref', () => {
    const { fixture, dialogRef } = build(['/a.jpg', '/b.jpg']);
    fixture.debugElement.nativeElement.querySelector('button[aria-label="dialog.close"]').click();
    expect(dialogRef.close).toHaveBeenCalled();
  });

  it('can inspect panes independently and deliberately reset them when relinking', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg']);
    const panes = () => fixture.debugElement.queryAll(By.directive(SyncedZoomComponent));
    const toggle = fixture.nativeElement.querySelector('[data-link-inspection]');
    expect(toggle).not.toBeNull();
    toggle.click();
    fixture.detectChanges();
    const next = { scale: 3, tx: 17, ty: -4 };
    panes()[1].componentInstance.zoomChange.emit(next);
    fixture.detectChanges();
    expect(panes()[0].componentInstance.zoom()).toEqual(FIT_ZOOM);
    expect(panes()[1].componentInstance.zoom()).toEqual(next);
    toggle.click();
    fixture.detectChanges();
    expect(panes().map(p => p.componentInstance.zoom())).toEqual([FIT_ZOOM, FIT_ZOOM]);
  });

  it('promotes a reference without changing pane membership or writing a review decision', () => {
    const paths = ['/a.jpg', '/b.jpg', '/c.jpg'];
    const { fixture, dialogRef } = build(paths);
    const reference = () => fixture.nativeElement.querySelector('[data-reference="true"]');
    expect(reference()).not.toBeNull();
    expect(reference().textContent).toContain('a.jpg');
    fixture.nativeElement.querySelectorAll('[data-promote-reference]')[0].click();
    fixture.detectChanges();
    expect(reference().textContent).toContain('b.jpg');
    expect(fixture.debugElement.queryAll(By.directive(SyncedZoomComponent)).map(p => p.componentInstance.frameKey())).toEqual(paths);
    expect(dialogRef.close).not.toHaveBeenCalled();
  });

  it('keeps sharp-preview readiness owned by its pane, including failure then recovery', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg']);
    const panes = fixture.debugElement.queryAll(By.directive(SyncedZoomComponent));
    panes[0].componentInstance.sharpFailed.emit('/a-preview');
    panes[1].componentInstance.sharpLoaded.emit('/b-preview');
    fixture.detectChanges();
    const statuses = () => Array.from(fixture.nativeElement.querySelectorAll('[data-preview-status]') as NodeListOf<HTMLElement>).map(p => p.textContent);
    expect(statuses()[0]).toContain('gallery.compare.preview_failed');
    expect(statuses()[1]).toContain('gallery.compare.preview_ready');
    panes[0].componentInstance.sharpPending.emit('/a-preview');
    fixture.detectChanges();
    expect(statuses()[0]).toContain('gallery.compare.preview_loading');
    panes[0].componentInstance.sharpLoaded.emit('/a-preview');
    fixture.detectChanges();
    expect(statuses()[0]).toContain('gallery.compare.preview_ready');
  });

  it('cycles only candidates in two-up mode and swaps the old reference back into the candidate slot on promotion', () => {
    const { fixture, dialogRef } = build(['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg']);
    const root = fixture.nativeElement as HTMLElement;
    const paths = () => fixture.debugElement.queryAll(By.directive(SyncedZoomComponent)).map(p => p.componentInstance.frameKey());
    expect(root.querySelector('[data-two-up]')).not.toBeNull();
    root.querySelector<HTMLButtonElement>('[data-two-up]')!.click();
    fixture.detectChanges();
    expect(paths()).toEqual(['/a.jpg', '/b.jpg']);
    expect(root.querySelector<HTMLButtonElement>('[data-candidate-previous]')!.disabled).toBe(true);
    root.querySelector<HTMLButtonElement>('[data-candidate-next]')!.click();
    fixture.detectChanges();
    expect(paths()).toEqual(['/a.jpg', '/c.jpg']);
    root.querySelector<HTMLButtonElement>('[data-promote-reference]')!.click();
    fixture.detectChanges();
    expect(paths()).toEqual(['/c.jpg', '/a.jpg']);
    root.querySelector<HTMLButtonElement>('[data-two-up]')!.click();
    fixture.detectChanges();
    expect(paths()).toEqual(['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg']);
    expect(dialogRef.close).not.toHaveBeenCalled();
  });

  it('moves candidates backward and stops at both boundaries without changing the reference', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg']);
    const root = fixture.nativeElement as HTMLElement;
    const paths = () => fixture.debugElement.queryAll(By.directive(SyncedZoomComponent)).map(p => p.componentInstance.frameKey());
    root.querySelector<HTMLButtonElement>('[data-two-up]')!.click();
    fixture.detectChanges();
    const previous = root.querySelector<HTMLButtonElement>('[data-candidate-previous]')!;
    const next = root.querySelector<HTMLButtonElement>('[data-candidate-next]')!;
    next.click(); fixture.detectChanges();
    next.click(); fixture.detectChanges();
    expect(paths()).toEqual(['/a.jpg', '/d.jpg']);
    expect(next.disabled).toBe(true);
    next.click(); fixture.detectChanges();
    expect(paths()).toEqual(['/a.jpg', '/d.jpg']);
    previous.click(); fixture.detectChanges();
    expect(paths()).toEqual(['/a.jpg', '/c.jpg']);
    previous.click(); fixture.detectChanges();
    expect(paths()).toEqual(['/a.jpg', '/b.jpg']);
    expect(previous.disabled).toBe(true);
    previous.click(); fixture.detectChanges();
    expect(paths()).toEqual(['/a.jpg', '/b.jpg']);
  });
  it('shows a thumbnail queue and opens a chosen candidate without promoting it', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg']);
    const root = fixture.nativeElement as HTMLElement;
    const queue = root.querySelectorAll<HTMLButtonElement>('[data-candidate-thumbnail]');
    expect(queue).toHaveLength(4);
    queue[3].click(); fixture.detectChanges();
    const panes = fixture.debugElement.queryAll(By.directive(SyncedZoomComponent));
    expect(panes.map(p => p.componentInstance.frameKey())).toEqual(['/a.jpg', '/d.jpg']);
    expect(root.querySelector('[data-reference="true"]')!.textContent).toContain('a.jpg');
    expect(root.querySelector('[data-candidate-thumbnail][aria-pressed="true"]')!.getAttribute('data-path')).toBe('/d.jpg');
  });

  it('removes the reference from this view only, chooses a surviving reference and can restore the original set', () => {
    const { fixture, dialogRef } = build(['/a.jpg', '/b.jpg', '/c.jpg']);
    const data = TestBed.inject(MAT_DIALOG_DATA);
    data.photos[0].is_rejected = false;
    data.photos[1].is_kept = true;
    const before = JSON.stringify(data.photos);
    const root = fixture.nativeElement as HTMLElement;
    root.querySelector<HTMLButtonElement>('[data-remove-pane]')!.click(); fixture.detectChanges();
    expect(fixture.debugElement.queryAll(By.directive(SyncedZoomComponent)).map(p => p.componentInstance.frameKey())).toEqual(['/b.jpg', '/c.jpg']);
    expect(root.querySelector('[data-reference="true"]')!.textContent).toContain('b.jpg');
    expect(root.querySelectorAll('[data-candidate-thumbnail]')).toHaveLength(2);
    root.querySelector<HTMLButtonElement>('[data-restore-comparison]')!.click(); fixture.detectChanges();
    expect(fixture.debugElement.queryAll(By.directive(SyncedZoomComponent)).map(p => p.componentInstance.frameKey())).toEqual(['/a.jpg', '/b.jpg', '/c.jpg']);
    expect(JSON.stringify(data.photos)).toBe(before);
    expect(dialogRef.close).not.toHaveBeenCalled();
  });

  it('advances after removing a candidate and keeps one remaining photo inspectable', () => {
    const { fixture, dialogRef } = build(['/a.jpg', '/b.jpg', '/c.jpg']);
    const root = fixture.nativeElement as HTMLElement;
    const paths = () => fixture.debugElement.queryAll(By.directive(SyncedZoomComponent)).map(p => p.componentInstance.frameKey());
    root.querySelectorAll<HTMLButtonElement>('[data-candidate-thumbnail]')[1].click(); fixture.detectChanges();
    root.querySelectorAll<HTMLButtonElement>('[data-remove-pane]')[1].click(); fixture.detectChanges();
    expect(paths()).toEqual(['/a.jpg', '/c.jpg']);
    root.querySelectorAll<HTMLButtonElement>('[data-remove-pane]')[1].click(); fixture.detectChanges();
    expect(paths()).toEqual(['/a.jpg']);
    expect(root.querySelector<HTMLButtonElement>('[data-remove-pane]')!.disabled).toBe(true);
    expect(dialogRef.close).not.toHaveBeenCalled();
  });

});
