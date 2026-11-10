import { signal } from '@angular/core';
import { TestBed, ComponentFixture } from '@angular/core/testing';
import { ScanHistoryComponent } from './scan-history.component';
import { ScanService, RecordedScanRun, ScanRunHistory, ScanRetryPreview } from '../../core/services/scan.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';

function run(id: number, status = 'completed', failed = 0): RecordedScanRun {
  return { id, status, mode: 'multi-pass', started_at: '2026-11-01T12:00:00Z', finished_at: null, heartbeat_at: null,
    total_files: 4, processed_files: 3, failed_files: failed, retained_failure_records: failed,
    failure_stages: failed ? [{ stage: 'load', count: failed }] : [] };
}

describe('recorded scan history', () => {
  let fixture: ComponentFixture<ScanHistoryComponent>;
  let root: HTMLElement;
  let read: ReturnType<typeof vi.fn>;
  let previewRead: ReturnType<typeof vi.fn>;
  let apply: ReturnType<typeof vi.fn>;
  let receiptRead: ReturnType<typeof vi.fn>;
  let connect: ReturnType<typeof vi.fn>;
  let token: string;
  const plan: ScanRetryPreview = { plan_id: 'a'.repeat(32), run_id: 2, expires_in_seconds: 600,
    files: ['/photos/café.jpg', '/photos/two.jpg'], omissions: [{ reason: 'missing', count: 1 }] };
  const owner = signal('root');
  const status = signal<unknown>({ user_id: 'root' });
  beforeEach(() => {
    token = 'fixture-token';
    owner.set('root'); status.set({ user_id: 'root' });
    read = vi.fn(async (): Promise<ScanRunHistory> => ({ runs: [run(3, 'running'), run(2, 'completed', 2)], next_before: 2 }));
    previewRead = vi.fn(async () => plan);
    apply = vi.fn(async () => 'b'.repeat(32));
    receiptRead = vi.fn(async () => ({ state: 'spawned', job_id: 'b'.repeat(32) }));
    connect = vi.fn(async () => undefined);
    TestBed.configureTestingModule({ imports: [ScanHistoryComponent], providers: [
      { provide: ScanService, useValue: { canLaunch: () => true, loadHistory: read,
        previewRetry: previewRead, applyRetry: apply, loadRetryReceipt: receiptRead, connect } },
      { provide: AuthService, useValue: { identity: owner, status, get token() { return token; }, isEdition: () => false } },
      { provide: I18nService, useValue: { t: (key: string, params?: Record<string, unknown>) => key + (params ? ' ' + Object.values(params).join(' ') : ''), translations: signal({}), currentLang: signal('en') } },
    ] });
    fixture = TestBed.createComponent(ScanHistoryComponent); fixture.detectChanges(); root = fixture.nativeElement;
  });
  async function open() {
    root.querySelector('summary')!.click();
    await vi.waitFor(() => expect(read).toHaveBeenCalled());
    await Promise.resolve(); fixture.detectChanges();
  }
  function button(label: string): HTMLButtonElement {
    return [...root.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent?.includes(label))!;
  }
  it('loads on disclosure, distinguishes recorded failures, formats UTC dates and pages by cursor', async () => {
    expect(read).not.toHaveBeenCalled(); await open();
    expect(root.textContent).toContain('scan.history.completed_failures');
    expect(root.textContent).toContain('scan.history.states.running');
    expect(root.textContent).toContain('01/11/2026 12:00');
    expect(root.textContent).toContain('scan.history.stages.load');
    read.mockResolvedValueOnce({ runs: [run(1)], next_before: null });
    button('scan.history.older').click(); await Promise.resolve(); fixture.detectChanges();
    expect(read).toHaveBeenLastCalledWith(2);
    expect(root.querySelectorAll('ol > li')).toHaveLength(3);
    expect(root.textContent).not.toContain('scan.history.older');
  });
  it('retains loaded rows on read failure and recovers without pretending the history is empty', async () => {
    await open();
    read.mockRejectedValueOnce(new Error('offline'));
    button('scan.history.refresh').click(); await Promise.resolve(); fixture.detectChanges();
    expect(root.querySelector('[role="alert"]')?.textContent).toContain('scan.history.read_error');
    expect(root.querySelectorAll('ol > li')).toHaveLength(2);
    expect(root.textContent).not.toContain('scan.history.empty');
    read.mockResolvedValueOnce({ runs: [], next_before: null });
    button('scan.history.refresh').click(); await Promise.resolve(); fixture.detectChanges();
    expect(root.querySelector('[role="alert"]')).toBeNull();
    expect(root.textContent).toContain('scan.history.empty');
  });
  it('discards a pending prior-account response and clears private history', async () => {
    let finish!: (value: ScanRunHistory) => void;
    read.mockImplementationOnce(() => new Promise<ScanRunHistory>(resolve => { finish = resolve; }));
    await open();
    owner.set('other'); status.set({ user_id: 'other' }); fixture.detectChanges();
    finish({ runs: [run(999)], next_before: null }); await Promise.resolve(); fixture.detectChanges();
    expect(root.textContent).not.toContain('#999');
    expect(root.querySelectorAll('ol > li')).toHaveLength(0);
    expect(root.querySelector('[role="status"]')).toBeNull();
  });

  it('keeps scoring completion distinct from a recorded running pipeline and does not reload on its nested disclosure', async () => {
    read.mockResolvedValueOnce({ runs: [{ ...run(2), viewer_job_id: 'a'.repeat(32), job_status: 'running', job_phase: 'tagging', job_finished_at: null }], next_before: null });
    await open();
    expect(root.textContent).toContain('scan.history.states.completed');
    expect(root.textContent).toContain('scan.history.pipeline');
    expect(root.textContent).toContain('scan.history.states.running');
    expect(root.textContent).toContain('scan.phase.tagging');
    expect(root.textContent).toContain('a'.repeat(32));
    const nested = root.querySelector('ol details') as HTMLDetailsElement;
    nested.open = true;
    nested.dispatchEvent(new Event('toggle', { bubbles: true }));
    await Promise.resolve(); fixture.detectChanges();
    expect(read).toHaveBeenCalledTimes(1);
  });

  it('previews one ended run without starting, lists captured targets and Cancel never writes', async () => {
    await open();
    expect([...root.querySelectorAll('button')].filter(b => b.textContent?.includes('scan.retry.preview'))).toHaveLength(1);
    const trigger = button('scan.retry.preview'); trigger.focus(); trigger.click();
    await Promise.resolve(); fixture.detectChanges();
    expect(previewRead).toHaveBeenCalledWith(2);
    expect(apply).not.toHaveBeenCalled();
    expect(root.textContent).toContain('/photos/café.jpg');
    expect(root.textContent).toContain('scan.retry.omissions.missing');
    await vi.waitFor(() => expect(document.activeElement).toBe(root.querySelector('[data-retry-preview]')));
    button('ui.buttons.cancel').click(); fixture.detectChanges();
    expect(root.textContent).not.toContain('/photos/café.jpg');
    expect(apply).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(trigger);
  });

  it('confirms only captured plan, and an uncertain start recovers by receipt read without another Apply', async () => {
    await open();
    button('scan.retry.preview').click(); await Promise.resolve(); fixture.detectChanges();
    apply.mockRejectedValueOnce(new Error('lost response'));
    const submitted = vi.fn(); fixture.componentInstance.retrySubmitted.subscribe(submitted);
    button('scan.retry.apply').click(); await Promise.resolve(); fixture.detectChanges();
    expect(apply).toHaveBeenCalledExactlyOnceWith(plan.plan_id);
    expect(submitted).toHaveBeenCalledOnce();
    expect(root.textContent).toContain('scan.retry.unconfirmed');
    expect(button('scan.retry.preview').disabled).toBe(true);
    button('scan.retry.read_receipt').click(); await Promise.resolve(); fixture.detectChanges();
    expect(receiptRead).toHaveBeenCalledExactlyOnceWith(plan.plan_id);
    expect(connect).toHaveBeenCalledExactlyOnceWith(false);
    expect(apply).toHaveBeenCalledTimes(1);
  });

  it('reports an accepted retry even if the history disclosure is collapsed while it starts', async () => {
    await open();
    button('scan.retry.preview').click(); await Promise.resolve(); fixture.detectChanges();
    let finish!: (id: string) => void;
    apply.mockImplementationOnce(() => new Promise<string>(resolve => { finish = resolve; }));
    const accepted = vi.fn(); fixture.componentInstance.retryAccepted.subscribe(accepted);
    button('scan.retry.apply').click(); fixture.detectChanges();
    const disclosure = root.querySelector('details')!;
    disclosure.open = false; disclosure.dispatchEvent(new Event('toggle')); fixture.detectChanges();
    finish('b'.repeat(32)); await vi.waitFor(() => expect(accepted).toHaveBeenCalledWith('b'.repeat(32)));
  });

  it('drops a late retry preview on account change and removes private targets', async () => {
    await open();
    let finish!: (value: ScanRetryPreview) => void;
    previewRead.mockImplementationOnce(() => new Promise<ScanRetryPreview>(resolve => { finish = resolve; }));
    button('scan.retry.preview').click();
    owner.set('other'); status.set({ user_id: 'other' }); fixture.detectChanges();
    finish(plan); await Promise.resolve(); fixture.detectChanges();
    expect(root.textContent).not.toContain('/photos/');
    expect(apply).not.toHaveBeenCalled();
  });

  it('expires an unused preview and refuses to keep its Apply action available', async () => {
    await open();
    previewRead.mockResolvedValueOnce({ ...plan, expires_in_seconds: 0 });
    button('scan.retry.preview').click(); await Promise.resolve(); fixture.detectChanges();
    await vi.waitFor(() => { fixture.detectChanges(); expect(root.textContent).toContain('scan.retry.expired'); });
    expect([...root.querySelectorAll('button')].some(b => b.textContent?.includes('scan.retry.apply'))).toBe(false);
    expect(apply).not.toHaveBeenCalled();
  });

  it('refuses a token-only change before confirmation and clears the stale preview', async () => {
    await open(); button('scan.retry.preview').click(); await Promise.resolve(); fixture.detectChanges();
    token = 'rotated-token';
    button('scan.retry.apply').click(); await Promise.resolve(); fixture.detectChanges();
    expect(apply).not.toHaveBeenCalled();
    expect(root.textContent).not.toContain('/photos/');
  });

  for (const state of ['preview', 'refused']) {
    it(`offers a fresh preview only after the receipt confirms ${state}`, async () => {
      await open(); button('scan.retry.preview').click(); await Promise.resolve(); fixture.detectChanges();
      apply.mockRejectedValueOnce(new Error('lost response'));
      button('scan.retry.apply').click(); await Promise.resolve(); fixture.detectChanges();
      receiptRead.mockResolvedValueOnce({ state, job_id: null });
      button('scan.retry.read_receipt').click(); await Promise.resolve(); fixture.detectChanges();
      expect(root.textContent).toContain('scan.retry.not_started');
      expect(button('scan.retry.preview').disabled).toBe(false);
      expect(apply).toHaveBeenCalledTimes(1);
      expect(connect).not.toHaveBeenCalled();
    });
  }

  it('does not interpret an expired receipt as proof that no process started', async () => {
    await open(); button('scan.retry.preview').click(); await Promise.resolve(); fixture.detectChanges();
    apply.mockRejectedValueOnce(new Error('lost response'));
    button('scan.retry.apply').click(); await Promise.resolve(); fixture.detectChanges();
    receiptRead.mockRejectedValueOnce({ status: 410 });
    button('scan.retry.read_receipt').click(); await Promise.resolve(); fixture.detectChanges();
    expect(root.textContent).toContain('scan.retry.unconfirmed');
    expect(root.textContent).not.toContain('scan.retry.not_started');
    expect(button('scan.retry.preview').disabled).toBe(true);
    expect(apply).toHaveBeenCalledTimes(1);
  });
  it('reports preview failures, permits a fresh read, pages targets and restores focus on Escape', async () => {
    await open();
    previewRead.mockRejectedValueOnce(new Error('offline'));
    const trigger = button('scan.retry.preview'); trigger.click();
    await vi.waitFor(() => { fixture.detectChanges(); expect(root.textContent).toContain('scan.retry.preview_error'); });
    expect(root.querySelector('[data-retry-preview]')).toBeNull();
    expect(apply).not.toHaveBeenCalled();
    previewRead.mockResolvedValueOnce({ ...plan, files: Array.from({ length: 45 }, (_, index) => `/p${index}.jpg`) });
    trigger.click();
    await vi.waitFor(() => { fixture.detectChanges(); expect(root.querySelector('[data-retry-preview]')).not.toBeNull(); });
    const paths = () => root.querySelectorAll('[data-retry-preview] li');
    expect(paths()).toHaveLength(20);
    button('scan.retry.more_files').click(); fixture.detectChanges(); expect(paths()).toHaveLength(40);
    button('scan.retry.more_files').click(); fixture.detectChanges(); expect(paths()).toHaveLength(45);
    expect(root.textContent).not.toContain('scan.retry.more_files');
    const section = root.querySelector<HTMLElement>('[data-retry-preview]')!;
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    section.dispatchEvent(event); fixture.detectChanges();
    expect(event.defaultPrevented).toBe(true);
    expect(root.querySelector('[data-retry-preview]')).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(apply).not.toHaveBeenCalled();
  });

});
