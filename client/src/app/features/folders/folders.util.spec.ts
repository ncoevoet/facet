import { buildFolderBreadcrumbs, folderDisplayName } from './folders.util';

describe('buildFolderBreadcrumbs', () => {
  it('should return an empty array at root', () => {
    expect(buildFolderBreadcrumbs('')).toEqual([]);
  });

  it('should return one crumb for a single-level relative prefix', () => {
    expect(buildFolderBreadcrumbs('Holidays/')).toEqual([
      { name: 'Holidays', path: 'Holidays/' },
    ]);
  });

  it('should return nested crumbs for a deep relative prefix', () => {
    expect(buildFolderBreadcrumbs('2026/Summer/Beach/')).toEqual([
      { name: '2026', path: '2026/' },
      { name: 'Summer', path: '2026/Summer/' },
      { name: 'Beach', path: '2026/Summer/Beach/' },
    ]);
  });

  it('should preserve the leading slash of an absolute prefix', () => {
    expect(buildFolderBreadcrumbs('/photos/2026/')).toEqual([
      { name: 'photos', path: '/photos/' },
      { name: '2026', path: '/photos/2026/' },
    ]);
  });

  it('should preserve both slashes of a UNC prefix', () => {
    expect(buildFolderBreadcrumbs('//server/share/')).toEqual([
      { name: 'server', path: '//server/' },
      { name: 'share', path: '//server/share/' },
    ]);
  });

  it('should keep a Windows drive letter attached to its root', () => {
    expect(buildFolderBreadcrumbs('C:/photos/')).toEqual([
      { name: 'C:', path: 'C:/' },
      { name: 'photos', path: 'C:/photos/' },
    ]);
  });

  it('should tolerate a missing or repeated trailing slash', () => {
    expect(buildFolderBreadcrumbs('/photos/2026')).toEqual(buildFolderBreadcrumbs('/photos/2026///'));
  });
});

describe('folderDisplayName', () => {
  it('should return the last segment of a prefix', () => {
    expect(folderDisplayName('/photos/2026/Beach/')).toBe('Beach');
  });

  it('should tolerate a missing trailing slash', () => {
    expect(folderDisplayName('/photos/2026/Beach')).toBe('Beach');
  });

  it('should fall back to the prefix itself when there is no segment', () => {
    expect(folderDisplayName('/')).toBe('/');
  });
});
