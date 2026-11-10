import { HttpErrorResponse } from '@angular/common/http';
import { isDefinitiveRejection } from './write-rejection';

describe('isDefinitiveRejection', () => {
  it.each([400, 404, 409, 422, 499])('treats HTTP %s as a refusal that committed nothing', status => {
    expect(isDefinitiveRejection(new HttpErrorResponse({ status }))).toBe(true);
  });

  it.each([0, 399, 500, 503])('leaves HTTP %s uncertain', status => {
    expect(isDefinitiveRejection(new HttpErrorResponse({ status }))).toBe(false);
  });

  it('leaves a non-HTTP failure uncertain', () => {
    expect(isDefinitiveRejection(new Error('timeout'))).toBe(false);
  });
});
