import { HttpErrorResponse } from '@angular/common/http';
import { extractErrorDetail } from './http-error.util';

describe('extractErrorDetail', () => {
  it('returns a string detail field', () => {
    const error = new HttpErrorResponse({ error: { detail: 'target_dir is not an allowed export location' } });
    expect(extractErrorDetail(error)).toBe('target_dir is not an allowed export location');
  });

  it('falls back to a string message field when detail is absent', () => {
    const error = new HttpErrorResponse({ error: { message: 'something went wrong' } });
    expect(extractErrorDetail(error)).toBe('something went wrong');
  });

  it('prefers detail over message when both are present', () => {
    const error = new HttpErrorResponse({ error: { detail: 'the detail', message: 'the message' } });
    expect(extractErrorDetail(error)).toBe('the detail');
  });

  it('ignores a non-string detail (FastAPI validation error list)', () => {
    const error = new HttpErrorResponse({ error: { detail: [{ loc: ['body', 'target_dir'], msg: 'field required' }] } });
    expect(extractErrorDetail(error)).toBeUndefined();
  });

  it('ignores an object detail', () => {
    const error = new HttpErrorResponse({ error: { detail: { nested: true } } });
    expect(extractErrorDetail(error)).toBeUndefined();
  });

  it('returns undefined when there is no error body', () => {
    expect(extractErrorDetail(new HttpErrorResponse({}))).toBeUndefined();
  });

  it('returns undefined for a plain Error with no .error property', () => {
    expect(extractErrorDetail(new Error('boom'))).toBeUndefined();
  });

  it('returns undefined for null/undefined input', () => {
    expect(extractErrorDetail(null)).toBeUndefined();
    expect(extractErrorDetail(undefined)).toBeUndefined();
  });

  it('caps a pathological detail length', () => {
    const long = 'x'.repeat(1000);
    const error = new HttpErrorResponse({ error: { detail: long } });
    const result = extractErrorDetail(error);
    expect(result!.length).toBeLessThan(400);
    expect(result!.endsWith('…')).toBe(true);
  });
});
