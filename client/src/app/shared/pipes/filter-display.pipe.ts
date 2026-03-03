import { Pipe, PipeTransform } from '@angular/core';
import { GalleryFilters } from '../../features/gallery/gallery.store';

interface FilterDisplayDef {
  minKey: keyof GalleryFilters;
  maxKey: keyof GalleryFilters;
  sliderMin: number;
  sliderMax: number;
  displayPrefix?: string;
  displaySuffix?: string;
}

@Pipe({ name: 'filterDisplay', standalone: true, pure: true })
export class FilterDisplayPipe implements PipeTransform {
  transform(filters: GalleryFilters, def: FilterDisplayDef): string {
    const minVal = String(filters[def.minKey] || def.sliderMin);
    const maxVal = String(filters[def.maxKey] || def.sliderMax);
    const prefix = def.displayPrefix ?? '';
    const suffix = def.displaySuffix ?? '';
    return `${prefix}${minVal}-${maxVal}${suffix}`;
  }
}
