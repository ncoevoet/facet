import { Pipe, PipeTransform } from '@angular/core';
import { I18N } from '../../core/i18n/keys';
import type { SidecarJobStatus } from '../../core/services/export.service';

/** Preserve the backend state; qualify a terminal receipt with incomplete work. */
@Pipe({ name: 'sidecarJobLabel' })
export class SidecarJobLabelPipe implements PipeTransform {
  transform(job: SidecarJobStatus): string {
    if (job.state === 'running' && job.phase === 'validating') return I18N.export.jobs.validating;
    if (job.state === 'completed' && (job.errors > 0 || job.skipped > 0 || job.processed < job.total)) return I18N.export.jobs.partial;
    return I18N.export.jobs[job.state];
  }
}
