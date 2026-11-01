import type { GalleryMode, PanelActivation, TooltipMode } from './gallery-filters.util';

export type GalleryDisplayPreset = 'browse' | 'review' | 'organize';

export interface GalleryPresentation {
  mode: GalleryMode;
  cardWidth: number;
  hide_details: boolean;
  tooltip_mode: TooltipMode;
  panel_activation: PanelActivation;
}

/** Presentation only: this contract deliberately cannot express a predicate or sort. */
export function galleryPresentation(preset: GalleryDisplayPreset, dockDetails: boolean): GalleryPresentation {
  switch (preset) {
    case 'browse': return { mode: 'mosaic', cardWidth: 168, hide_details: true, tooltip_mode: dockDetails ? 'hover' : 'click', panel_activation: 'both' };
    case 'review': return { mode: 'grid', cardWidth: 240, hide_details: false, tooltip_mode: dockDetails ? 'panel' : 'click', panel_activation: 'click' };
    case 'organize': return { mode: 'list', cardWidth: 168, hide_details: false, tooltip_mode: 'click', panel_activation: 'click' };
  }
}
