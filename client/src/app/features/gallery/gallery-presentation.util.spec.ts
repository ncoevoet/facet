import { galleryPresentation } from './gallery-presentation.util';

describe('galleryPresentation', () => {
  it.each([false, true])('keeps presentation presets separate from criteria (dock available: %s)', dock => {
    expect(galleryPresentation('browse', dock)).toEqual({ mode: 'mosaic', cardWidth: 168, hide_details: true,
      tooltip_mode: dock ? 'hover' : 'click', panel_activation: 'both' });
    expect(galleryPresentation('review', dock)).toEqual({ mode: 'grid', cardWidth: 240, hide_details: false,
      tooltip_mode: dock ? 'panel' : 'click', panel_activation: 'click' });
    expect(galleryPresentation('organize', dock)).toEqual({ mode: 'list', cardWidth: 168, hide_details: false,
      tooltip_mode: 'click', panel_activation: 'click' });
  });
});
