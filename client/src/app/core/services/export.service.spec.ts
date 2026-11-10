import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApiService } from './api.service';
import { ExportService, SidecarJobStatus } from './export.service';

const JOB: SidecarJobStatus = { id: 'job', state: 'running', started_at: 1, total: 3, processed: 0, written: 0, skipped: 0, errors: 0 };

describe('ExportService background sidecars', () => {
  let service: ExportService;
  let http: HttpTestingController;
  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [ExportService, ApiService, provideHttpClient(withXhr()), provideHttpClientTesting()] });
    service = TestBed.inject(ExportService);
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => http.verify());

  it('keeps status and recent reads separate from explicit cancel and retry previews', () => {
    service.recentSidecarJobs().subscribe();
    const recent = http.expectOne('/api/export/sidecar_jobs');
    expect(recent.request.method).toBe('GET'); recent.flush([JOB]);
    service.sidecarJob('a/b').subscribe();
    const status = http.expectOne('/api/export/sidecar_jobs/a%2Fb');
    expect(status.request.method).toBe('GET'); status.flush(JOB);
    service.cancelSidecarJob('a/b').subscribe();
    const cancel = http.expectOne('/api/export/sidecar_jobs/a%2Fb/cancel');
    expect(cancel.request.method).toBe('POST'); cancel.flush({ ...JOB, cancel_requested: true });
    service.previewRetry('a/b').subscribe();
    const retry = http.expectOne('/api/export/sidecar_jobs/a%2Fb/preview');
    expect(retry.request.method).toBe('POST'); retry.flush({ ...JOB, id: 'retry' }, { status: 202, statusText: 'Accepted' });
  });

});
