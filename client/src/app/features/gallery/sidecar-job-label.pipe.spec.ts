import { SidecarJobLabelPipe } from './sidecar-job-label.pipe';
import type { SidecarJobStatus } from '../../core/services/export.service';

describe('SidecarJobLabelPipe', () => {
  const pipe = new SidecarJobLabelPipe();
  const job: SidecarJobStatus = { id: 'receipt', state: 'completed', started_at: 1,
    total: 2, processed: 2, written: 2, skipped: 0, errors: 0 };

  it('distinguishes validation from ordinary running work', () => {
    expect(pipe.transform({ ...job, state: 'running', phase: 'validating' })).toBe('export.jobs.validating');
    expect(pipe.transform({ ...job, state: 'running' })).toBe('export.jobs.running');
  });

  it.each([{ errors: 1 }, { skipped: 1 }, { processed: 1 }])('qualifies incomplete terminal receipts: %j', partial => {
    expect(pipe.transform({ ...job, ...partial })).toBe('export.jobs.partial');
  });

  it('preserves complete and cancelled states', () => {
    expect(pipe.transform(job)).toBe('export.jobs.completed');
    expect(pipe.transform({ ...job, state: 'cancelled', processed: 1 })).toBe('export.jobs.cancelled');
  });
});
