import { downloadCsv } from './csv';

describe('downloadCsv', () => {
  let lastCsv: string | null;
  let downloads: string[];
  let origBlob: typeof Blob;
  let origCreateObjectURL: typeof URL.createObjectURL;
  let origRevokeObjectURL: typeof URL.revokeObjectURL;

  beforeEach(() => {
    lastCsv = null;
    downloads = [];
    origBlob = globalThis.Blob;
    origCreateObjectURL = URL.createObjectURL;
    origRevokeObjectURL = URL.revokeObjectURL;
    // Capture the text handed to the Blob constructor — jsdom's Blob has no
    // readable .text()/.arrayBuffer(), so inspect the input instead.
    globalThis.Blob = function (parts: BlobPart[], opts?: BlobPropertyBag) {
      lastCsv = parts && parts.length ? String(parts[0]) : '';
      return new origBlob(parts, opts);
    } as unknown as typeof Blob;
    URL.createObjectURL = jest.fn(() => 'blob:mock');
    URL.revokeObjectURL = jest.fn();
    jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      downloads.push(this.download);
    });
  });

  afterEach(() => {
    globalThis.Blob = origBlob;
    URL.createObjectURL = origCreateObjectURL;
    URL.revokeObjectURL = origRevokeObjectURL;
    jest.restoreAllMocks();
  });

  const BOM = String.fromCharCode(0xfeff);

  /** Lines of the most recent CSV, BOM stripped. */
  function lines(): string[] {
    if (lastCsv === null) throw new Error('no CSV produced');
    return (lastCsv.startsWith(BOM) ? lastCsv.slice(1) : lastCsv).split('\r\n');
  }

  it('is a no-op for an empty array', () => {
    downloadCsv('empty', []);
    expect(lastCsv).toBeNull();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(downloads).toEqual([]);
  });

  it('derives the header from the first row keys and writes one line per row', () => {
    downloadCsv('data', [{ a: 1, b: 'two' }, { a: 3, b: 'four' }]);
    expect(lines()).toEqual(['a,b', '1,two', '3,four']);
  });

  it('quotes fields containing commas, quotes, or newlines (RFC 4180)', () => {
    downloadCsv('q', [{ a: 'x,y', b: 'he said "hi"', c: 'line1\nline2' }]);
    expect(lines()[1]).toBe('"x,y","he said ""hi""","line1\nline2"');
  });

  it('emits an empty cell for null and undefined values', () => {
    downloadCsv('n', [{ a: null, b: undefined, c: 0 }]);
    expect(lines()[1]).toBe(',,0');
  });

  it('skips non-scalar columns (nested arrays/objects)', () => {
    downloadCsv('s', [{ name: 'cam', count: 5, history: [1, 2], meta: { x: 1 } }]);
    expect(lines()[0]).toBe('name,count');
    expect(lines()[1]).toBe('cam,5');
  });

  it('appends a .csv extension only when missing', () => {
    downloadCsv('report', [{ a: 1 }]);
    downloadCsv('report.csv', [{ a: 1 }]);
    expect(downloads).toEqual(['report.csv', 'report.csv']);
  });

  it('prepends a UTF-8 BOM so spreadsheet apps detect the encoding', () => {
    downloadCsv('bom', [{ a: 1 }]);
    expect(lastCsv!.charCodeAt(0)).toBe(0xfeff);
  });

  it('revokes the object URL after triggering the download', () => {
    downloadCsv('cleanup', [{ a: 1 }]);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock');
  });
});
