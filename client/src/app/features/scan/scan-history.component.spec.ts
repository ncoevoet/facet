import { signal } from '@angular/core';
import { TestBed, ComponentFixture } from '@angular/core/testing';
import { ScanHistoryComponent } from './scan-history.component';
import { ScanService, RecordedScanRun, ScanRunHistory } from '../../core/services/scan.service';
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
  const owner = signal('root');
  const status = signal<unknown>({ user_id: 'root' });
  beforeEach(() => {
    owner.set('root'); status.set({ user_id: 'root' });
    read = vi.fn(async (): Promise<ScanRunHistory> => ({ runs: [run(3, 'running'), run(2, 'completed', 2)], next_before: 2 }));
    TestBed.configureTestingModule({ imports: [ScanHistoryComponent], providers: [
      { provide: ScanService, useValue: { canLaunch: () => true, loadHistory: read } },
      { provide: AuthService, useValue: { identity: owner, status, token: 'fixture-token', isEdition: () => false } },
      { provide: I18nService, useValue: { t: (key: string) => key, translations: signal({}), currentLang: signal('en') } },
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
});
