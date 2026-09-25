import { HttpErrorResponse } from '@angular/common/http';

import { isBracketLadderRejection } from './sequence-ladder';

describe('isBracketLadderRejection', () => {
  it('is true for a bracket kind rejected with a 400', () => {
    expect(isBracketLadderRejection('bracket', new HttpErrorResponse({ status: 400 }))).toBe(true);
  });

  it('is false for a bracket kind rejected with a non-400 status', () => {
    expect(isBracketLadderRejection('bracket', new HttpErrorResponse({ status: 500 }))).toBe(false);
  });

  it('is false for a bracket kind with a non-HTTP error', () => {
    expect(isBracketLadderRejection('bracket', new Error('nope'))).toBe(false);
  });

  it('is false for a panorama kind even on a 400', () => {
    expect(isBracketLadderRejection('panorama', new HttpErrorResponse({ status: 400 }))).toBe(false);
  });

  it('is false when kind is undefined', () => {
    expect(isBracketLadderRejection(undefined, new HttpErrorResponse({ status: 400 }))).toBe(false);
  });
});
