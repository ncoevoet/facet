import { FilenamePipe } from './filename.pipe';

describe('FilenamePipe', () => {
  const pipe = new FilenamePipe();
  it.each([
    ['/photos/trip/take-1.jpg', 'take-1.jpg'],
    ['C:\\Photos\\Trip\\take-2.jpg', 'take-2.jpg'],
    ['C:\\Photos/mixed\\take-3.jpg', 'take-3.jpg'],
    ['写真 é space.jpg', '写真 é space.jpg'],
    ['/写真/é & <portrait>.jpg', 'é & <portrait>.jpg'],
    ['', ''],
  ])('displays the filename for %s', (path, expected) => {
    expect(pipe.transform(path)).toBe(expected);
  });
  it('retains distinct caller paths even when their display names match', () => {
    const paths = ['/first/same.jpg', '/second/same.jpg'];
    expect(paths.map(path => pipe.transform(path))).toEqual(['same.jpg', 'same.jpg']);
    expect(paths).toEqual(['/first/same.jpg', '/second/same.jpg']);
  });
  it('retains distinguishing suffixes without splitting Unicode code points', () => {
    const name = '📷'.repeat(50) + '_final_v3_EXPORT_for_print_A2.jpg';
    const compact = pipe.transform(name, 64);
    expect(Array.from(compact)).toHaveLength(64);
    expect(compact).toContain('…');
    expect(compact.endsWith('final_v3_EXPORT_for_print_A2.jpg')).toBe(true);
    expect(compact).not.toContain('\uFFFD');
  });
});
