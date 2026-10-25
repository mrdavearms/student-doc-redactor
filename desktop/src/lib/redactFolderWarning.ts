/** Whether the redact completion screen warns that the output folder is not safe to share.
 *  Anything other than an explicit `false` warns, so a missing field never reassures. */
export function showFolderHoldsOriginals(holdsOriginals: boolean | undefined): boolean {
  return holdsOriginals !== false;
}
