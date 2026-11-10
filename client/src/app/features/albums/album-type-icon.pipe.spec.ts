import { MarkTonePipe } from '../../shared/pipes/mark-tone.pipe';
import { AlbumTypeIconPipe } from './album-type-icon.pipe';

describe('AlbumTypeIconPipe', () => {
  const pipe = new AlbumTypeIconPipe();

  it('uses the library icon for All', () => {
    expect(pipe.transform('')).toEqual({ text: 'photo_library', classes: '' });
  });

  it('uses the album icon for manual albums', () => {
    expect(pipe.transform('manual')).toEqual({ text: 'photo_album', classes: '' });
  });

  it('draws smart albums with the smart-coloured mark the cards show', () => {
    expect(pipe.transform('smart')).toEqual({ text: '✦', classes: new MarkTonePipe().transform('smart') });
  });

  it('falls back to the All icon for an unknown type', () => {
    expect(pipe.transform('weird')).toEqual({ text: 'photo_library', classes: '' });
  });
});
