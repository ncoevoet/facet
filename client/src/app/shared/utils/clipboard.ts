export function basename(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

export function copyLines(lines: string[]): Promise<void> {
  return navigator.clipboard.writeText(lines.join('\n'));
}
