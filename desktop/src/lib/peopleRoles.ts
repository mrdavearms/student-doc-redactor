/**
 * The role map a run will actually use: what the screen DISPLAYS.
 *
 * The dropdown renders the explicit answer if there is one, else the
 * suggestion — so Continue must commit exactly that, or the screen lies
 * (dropdown says Teacher, output says [Other person]). Ignored people are
 * excluded; they are not people.
 */
import type { PersonInfo } from '../types';

export function effectiveRoleMap(
  people: PersonInfo[],
  explicit: Record<string, string>,
  ignored: string[],
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const p of people) {
    if (ignored.includes(p.full_name)) continue;
    out[p.full_name] = explicit[p.full_name] ?? p.suggested_role;
  }
  return out;
}
