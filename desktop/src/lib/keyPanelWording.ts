export type KeyPanelWording = 'holds-originals' | 'review-first' | 'safe';

/** Which sentence the key-file panel shows. Never reassures when anything is unresolved. */
export function keyPanelWording(holdsOriginals: boolean, hasFailures: boolean): KeyPanelWording {
  if (holdsOriginals) return 'holds-originals';
  if (hasFailures) return 'review-first';
  return 'safe';
}
