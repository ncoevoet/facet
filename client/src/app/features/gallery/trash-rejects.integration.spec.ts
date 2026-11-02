import { Location } from '@angular/common';
import { provideLocationMocks, SpyLocation } from '@angular/common/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { NavigationStart, provideRouter, Router } from '@angular/router';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Subject } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { CullDialogComponent } from './cull-dialog.component';

const DIGEST = 'a'.repeat(64);
const FILTERS = { show_rejected: '1', type: '', hide_blinks: 'false', hide_bursts: 'false',
  hide_duplicates: 'false', hide_brackets: 'false', hide_panoramas: 'false' };

describe('all rejected photos preview and apply through HTTP', () => {
  let fixture: ComponentFixture<CullDialogComponent>;
  let http: HttpTestingController;
  let owner: ReturnType<typeof signal<string>>;
  let edition: ReturnType<typeof signal<boolean>>;
  let beforeClosed: Subject<void>;
  let close: ReturnType<typeof vi.fn>;
  let toast: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    owner = signal('alice'); edition = signal(true); beforeClosed = new Subject<void>();
    close = vi.fn(() => beforeClosed.next()); toast = vi.fn();
    TestBed.configureTestingModule({
      imports: [CullDialogComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting(),
        { provide: AuthService, useValue: { identity: owner, isEdition: edition } },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
        { provide: MatSnackBar, useValue: { open: toast } },
        { provide: MatDialogRef, useValue: { close, beforeClosed: () => beforeClosed } },
        { provide: MAT_DIALOG_DATA, useValue: { paths: [], filters: FILTERS,
          trashAvailable: true, action: 'trash_rejects', allRejects: true } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(CullDialogComponent);
    fixture.detectChanges();
  });

  afterEach(() => {
    fixture.destroy();
    http.verify();
  });

  const applyButton = () => fixture.nativeElement.querySelector('button[mat-flat-button]') as HTMLButtonElement;

  async function preview(digest: string | undefined = DIGEST) {
    const request = http.expectOne('/api/cull/apply');
    expect(request.request.body).toMatchObject({ filters: FILTERS, action: 'trash_rejects', dry_run: true,
      include_companions: false, include_sequence_siblings: false });
    expect(request.request.body.paths).toBeUndefined();
    request.flush({ preview_digest: digest, would_trash: ['/r.jpg'], skipped: [], matched: 1 });
    await fixture.whenStable(); fixture.detectChanges();
  }

  it('previews on open and sends the reviewed digest only on an explicit Apply click', async () => {
    expect(applyButton().disabled).toBe(true);
    expect(fixture.nativeElement.textContent).toContain('cull.trash_all_rejects');
    expect(fixture.nativeElement.textContent).toContain('cull.all_rejects_scope');
    await preview();
    expect(applyButton().disabled).toBe(false);
    applyButton().click();
    const apply = http.expectOne('/api/cull/apply');
    expect(apply.request.body).toMatchObject({ filters: FILTERS, dry_run: false, preview_digest: DIGEST });
    apply.flush({ trashed: 1, errors: 0 });
    await fixture.whenStable();
    expect(close).toHaveBeenCalledWith(true);
  });

  it('requires a digest in the all-rejects preview before enabling Apply', async () => {
    const request = http.expectOne('/api/cull/apply');
    request.flush({ would_trash: ['/r.jpg'], skipped: [], matched: 1 });
    await fixture.whenStable(); fixture.detectChanges();
    expect(applyButton().disabled).toBe(true);
    await fixture.componentInstance.apply();
    http.expectNone('/api/cull/apply');
  });

  it('shows exactly the HTTP dry-run targets, including companions, before applying the same digest', async () => {
    const request = http.expectOne('/api/cull/apply');
    request.flush({ preview_digest: DIGEST, would_trash: ['/r.jpg', '/r.CR3', '/r.XMP'], matched: 1 });
    await fixture.whenStable(); fixture.detectChanges();
    const rows = fixture.nativeElement.querySelectorAll('app-cull-file-preview li') as NodeListOf<HTMLElement>;
    expect([...rows].map(row => row.querySelector('p')?.textContent?.trim())).toEqual(['/r.jpg', '/r.CR3', '/r.XMP']);
    expect(applyButton().textContent?.trim()).toBe('cull.file_preview.trash');
    http.expectNone('/api/cull/apply');
    applyButton().click();
    const apply = http.expectOne('/api/cull/apply');
    expect(apply.request.body).toMatchObject({ dry_run: false, preview_digest: DIGEST, filters: FILTERS });
    apply.flush({ trashed: 3 }); await fixture.whenStable();
    expect(close).toHaveBeenCalledWith(true);
  });

  it('does not apply without a successful preview, even if the method is called directly', async () => {
    const initial = http.expectOne('/api/cull/apply');
    await fixture.componentInstance.apply();
    http.expectNone('/api/cull/apply');
    initial.flush({ would_trash: [], preview_digest: DIGEST });
    await fixture.whenStable();
  });

  it.each(['account', 'edition', 'dismiss', 'destroy'])(
    'ignores preview completion and refuses Apply after %s changes', async change => {
      const initial = http.expectOne('/api/cull/apply');
      if (change === 'account') owner.set('bob');
      else if (change === 'edition') edition.set(false);
      else if (change === 'dismiss') beforeClosed.next();
      else fixture.destroy();
      initial.flush({ would_trash: ['/private.jpg'], preview_digest: DIGEST });
      await fixture.componentInstance.apply();
      http.expectNone('/api/cull/apply');
      expect(toast).not.toHaveBeenCalled();
      expect((fixture.componentInstance as unknown as { preview(): unknown }).preview()).toBeNull();
    },
  );

  it('refuses Apply immediately after an account change before auth effects run', async () => {
    await preview(); owner.set('bob');
    await fixture.componentInstance.apply();
    http.expectNone('/api/cull/apply');
  });

  it('closes on real router navigation before allowing a stale Apply', async () => {
    await preview();
    await TestBed.inject(Router).navigateByUrl('/?other=1');
    await fixture.componentInstance.apply();
    expect(close).toHaveBeenCalled();
    http.expectNone('/api/cull/apply');
  });

  it('explains how to split an oversized global scope without suggesting ignored filters', async () => {
    http.expectOne('/api/cull/apply').flush({ detail: 'Narrow the filters and try again' },
      { status: 412, statusText: 'Precondition Failed' });
    await fixture.whenStable(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('cull.all_rejects_limit');
    expect(fixture.nativeElement.textContent).not.toContain('Narrow the filters and try again');
    expect(applyButton().disabled).toBe(true);
    await fixture.componentInstance.apply();
    http.expectNone('/api/cull/apply');
  });

  it.each(['success', 'partial', 'error'])(
    'retains the %s outcome when navigation completes during Apply', async outcome => {
      await preview();
      const pending = fixture.componentInstance.apply();
      const request = http.expectOne('/api/cull/apply');
      await TestBed.inject(Router).navigateByUrl('/?other=1');
      fixture.detectChanges();
      expect(close).not.toHaveBeenCalled();
      if (outcome === 'error') request.flush({ detail: 'retry required' },
        { status: 503, statusText: 'Unavailable' });
      else request.flush({ trashed: 1, errors: outcome === 'partial' ? 1 : 0 });
      await pending; fixture.detectChanges();
      if (outcome === 'success') {
        expect(close).toHaveBeenCalledWith(true);
        expect(toast).toHaveBeenCalledWith('cull.done', '', expect.anything());
      } else {
        expect(close).not.toHaveBeenCalled();
        expect(fixture.nativeElement.textContent).toContain(outcome === 'partial' ? 'cull.partial_error' : 'retry required');
        expect(applyButton().disabled).toBe(true);
        const retry = fixture.componentInstance.runPreview();
        await preview('b'.repeat(64)); await retry;
        expect(applyButton().disabled).toBe(false);
      }
    },
  );

  it('keeps partial failures open and requires a fresh preview before a successful retry', async () => {
    await preview();
    const first = fixture.componentInstance.apply();
    http.expectOne('/api/cull/apply').flush({ trashed: 1, errors: 1 });
    await first; fixture.detectChanges();
    expect(close).not.toHaveBeenCalled();
    expect(fixture.nativeElement.textContent).toContain('cull.partial_error');
    expect(toast).not.toHaveBeenCalledWith('cull.done', '', expect.anything());
    expect(applyButton().disabled).toBe(true);
    await fixture.componentInstance.apply(); http.expectNone('/api/cull/apply');
    const again = fixture.componentInstance.runPreview();
    await preview('b'.repeat(64)); await again;
    const retry = fixture.componentInstance.apply();
    const request = http.expectOne('/api/cull/apply');
    expect(request.request.body.preview_digest).toBe('b'.repeat(64));
    request.flush({ trashed: 1, errors: 0 }); await retry;
    expect(close).toHaveBeenCalledWith(true);
  });

  it.each(['account', 'dismiss', 'destroy'])(
    'does not announce an old apply result after %s changes', async change => {
      await preview();
      const pending = fixture.componentInstance.apply();
      const apply = http.expectOne('/api/cull/apply');
      await fixture.componentInstance.apply();
      http.expectNone('/api/cull/apply');
      if (change === 'account') owner.set('bob');
      else if (change === 'dismiss') beforeClosed.next();
      else fixture.destroy();
      apply.flush({ trashed: 1, errors: 0 }); await pending;
      expect(toast).not.toHaveBeenCalled();
      expect(close).not.toHaveBeenCalledWith(true);
    },
  );

  it('a changed-scope refusal clears the preview and can be retried after another preview', async () => {
    await preview();
    const apply = fixture.componentInstance.apply();
    http.expectOne('/api/cull/apply').flush({ detail: 'Culling preview changed. Preview again before applying.' },
      { status: 409, statusText: 'Conflict' });
    await apply; fixture.detectChanges();
    expect(applyButton().disabled).toBe(true);
    expect(close).not.toHaveBeenCalled();
    const retry = fixture.componentInstance.runPreview(); await preview(); await retry;
    expect(applyButton().disabled).toBe(false);
  });
});

describe('trash Apply with a real Material dialog', () => {
  it('keeps a real dialog open across Apply navigation and Escape, then permits dismissal after partial failure', async () => {
    const { MatDialog, MatDialogState } = await import('@angular/material/dialog');
    TestBed.configureTestingModule({
      imports: [CullDialogComponent],
      providers: [provideRouter([]), provideLocationMocks(), provideHttpClient(), provideHttpClientTesting(),
        { provide: AuthService, useValue: { identity: () => 'alice', isEdition: () => true } },
        { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
      ],
    });
    const http = TestBed.inject(HttpTestingController);
    const ref = TestBed.inject(MatDialog).open(CullDialogComponent, {
      closeOnNavigation: false,
      data: { paths: [], filters: FILTERS, trashAvailable: true, action: 'trash_rejects', allRejects: true },
    });
    const initial = http.expectOne('/api/cull/apply');
    initial.flush({ would_trash: ['/r.jpg'], skipped: [], matched: 1, preview_digest: DIGEST });
    await vi.waitFor(() => expect(ref.getState()).toBe(MatDialogState.OPEN));
    const container = document.querySelector('mat-dialog-container')!;
    const heading = container.querySelector('h2')!;
    const button = (label: string) => [...container.querySelectorAll('button')]
      .find(item => item.textContent?.trim() === label) as HTMLButtonElement;
    await vi.waitFor(() => expect(button('cull.file_preview.trash_one').disabled).toBe(false));
    button('cull.file_preview.trash_one').click();
    const apply = http.expectOne('/api/cull/apply');
    expect(ref.disableClose).toBe(true);
    await TestBed.inject(Router).navigateByUrl('/?duringApply=1');
    expect(ref.getState()).toBe(MatDialogState.OPEN);
    TestBed.inject(Router).setUpLocationChangeListener();
    const starts: NavigationStart[] = [];
    const navigation = TestBed.inject(Router).events.subscribe(event => {
      if (event instanceof NavigationStart) starts.push(event);
    });
    (TestBed.inject(Location) as SpyLocation).simulateUrlPop('/');
    await vi.waitFor(() => expect(TestBed.inject(Router).url).toBe('/'));
    expect(starts.at(-1)?.navigationTrigger).toBe('popstate');
    navigation.unsubscribe();
    expect(ref.getState()).toBe(MatDialogState.OPEN);
    await vi.waitFor(() => expect(button('cull.cancel').disabled).toBe(true));
    heading.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true, cancelable: true }));
    expect(ref.getState()).toBe(MatDialogState.OPEN);
    apply.flush({ trashed: 0, errors: 1 });
    await vi.waitFor(() => expect(ref.disableClose).not.toBe(true));
    await vi.waitFor(() => expect(button('cull.cancel').disabled).toBe(false));
    expect(ref.getState()).toBe(MatDialogState.OPEN);
    heading.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(ref.getState()).not.toBe(MatDialogState.OPEN));
    http.verify();
  });
});
