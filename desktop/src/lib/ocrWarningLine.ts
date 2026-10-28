/** One line of the redact completion screen's scanned-pages panel.
 *  `count` is the selected items on image-only pages; it is 0 when the only
 *  warning is the common-word note, and "0 item(s)" would read as all clear. */
export function ocrWarningLine(filename: string, count: number): string {
  if (count === 0) return `${filename}: has scanned pages to check`;
  return `${filename}: ${count} item(s) on image-only pages`;
}
