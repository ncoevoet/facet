import { Pipe, PipeTransform } from '@angular/core';

@Pipe({ name: 'apertureFormat', standalone: true, pure: true })
export class ApertureFormatPipe implements PipeTransform {
  transform(value: number | null | undefined): string {
    if (value == null || isNaN(value)) return '';
    return 'f/' + (Number.isInteger(value) ? value.toString() : value.toFixed(1));
  }
}

@Pipe({ name: 'focalLengthFormat', standalone: true, pure: true })
export class FocalLengthFormatPipe implements PipeTransform {
  transform(value: number | null | undefined): string {
    if (value == null || isNaN(value)) return '';
    return (Number.isInteger(value) ? value.toString() : value.toFixed(0)) + 'mm';
  }
}

@Pipe({ name: 'isoFormat', standalone: true, pure: true })
export class IsoFormatPipe implements PipeTransform {
  transform(value: number | null | undefined): string {
    if (value == null || isNaN(value)) return '';
    return 'ISO ' + Math.round(value).toLocaleString();
  }
}

@Pipe({ name: 'luminanceFormat', standalone: true, pure: true })
export class LuminanceFormatPipe implements PipeTransform {
  transform(value: number | null | undefined): string {
    if (value == null || isNaN(value)) return '';
    return Math.round(value * 100) + '%';
  }
}

@Pipe({ name: 'faceRatioFormat', standalone: true, pure: true })
export class FaceRatioFormatPipe implements PipeTransform {
  transform(value: number | null | undefined): string {
    if (value == null || isNaN(value)) return '';
    return Math.round(value * 100) + '%';
  }
}
