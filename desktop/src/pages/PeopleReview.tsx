import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { ArrowLeft, ArrowRight, HelpCircle, UserRound, Check } from 'lucide-react';
import { useStore } from '../store';
import { api } from '../api';
import { friendlyError } from '../lib/errorMessage';
import type { PersonInfo } from '../types';
import { effectiveRoleMap } from '../lib/peopleRoles';

const IGNORE = '__ignore__';
const CUSTOM = '__custom__';

export default function PeopleReview() {
  const {
    detectionResults, userSelections, folderPath, studentName,
    parentNames, familyNames, organisationNames, redactHeaderFooter,
    personRoles, personCustomLabels, ignoredPeople, inputMode, workflowMode,
    navigateTo, setError, setPersonRole, setPersonIgnored,
    acceptSuggestedRoles, peopleAutoSkippedKey, setPeopleAutoSkippedKey,
  } = useStore();

  const isPaste = inputMode === 'paste';
  const fetchPeople = isPaste ? api.textPeople : api.deidentifyPeople;
  const fetchLabels = isPaste ? api.textLabels : api.deidentifyLabels;

  const [people, setPeople] = useState<PersonInfo[] | null>(null);
  const [roleOptions, setRoleOptions] = useState<{ key: string; label: string }[]>([]);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [customOpen, setCustomOpen] = useState<Record<string, boolean>>({});
  const skipKey = useRef('');

  const requestBody = useCallback(() => {
    const selectedKeys: string[] = [];
    for (const doc of detectionResults?.documents ?? []) {
      doc.matches.forEach((_, idx) => {
        const key = `${doc.path}_${idx}`;
        if (userSelections[key]) selectedKeys.push(key);
      });
    }
    const split = (s: string) => s.split(',').map((n) => n.trim()).filter(Boolean);
    const body: Record<string, unknown> = {
      mode: workflowMode,
      folder_path: folderPath,
      student_name: studentName,
      parent_names: split(parentNames),
      family_names: split(familyNames),
      organisation_names: split(organisationNames),
      redact_header_footer: redactHeaderFooter,
      documents: (detectionResults?.documents ?? []).map((d) => d.path),
      selected_keys: selectedKeys,
      folder_action: null,
      // The preview must show what a run would produce, and a run uses the
      // DISPLAYED values (suggestions included) — see effectiveRoleMap.
      person_roles: people
        ? effectiveRoleMap(people, personRoles, ignoredPeople)
        : personRoles,
      person_custom_labels: personCustomLabels,
      ignored_people: ignoredPeople,
    };
    // The paste endpoints build folder_path/documents/folder_action/
    // custom_output_* themselves — a paste has none of those, and the
    // renderer must never fabricate one.
    if (isPaste) {
      delete body.folder_path;
      delete body.documents;
      delete body.folder_action;
      delete body.custom_output_path;
      delete body.custom_output_filename;
    }
    return body;
  }, [detectionResults, userSelections, folderPath, studentName, parentNames,
      familyNames, organisationNames, redactHeaderFooter, personRoles,
      personCustomLabels, ignoredPeople, people, isPaste, workflowMode]);

  // Load the people once on mount.
  useEffect(() => {
    let cancelled = false;
    fetchPeople(requestBody())
      .then((res) => {
        if (cancelled) return;
        setPeople(res.people);
        setRoleOptions(res.roles);
        setLabels(Object.fromEntries(res.people.map((p) => [p.full_name, p.label])));
      })
      .catch((e) => {
        if (cancelled) return;
        // The backend cache may be gone — force a fresh detection next time,
        // or the wizard loops with no way forward (CLAUDE.md rule 41).
        if (/no cached detection data/i.test((e as Error)?.message ?? '')) {
          useStore.getState().setDetectionParamsKey('');
        }
        setError(friendlyError(e));
        setPeople([]);
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Labels are recomputed by the backend on every change: reassigning one
  // person can renumber every other person sharing that role, so the whole set
  // has to come back, and the numbering rules must live in exactly one place.
  useEffect(() => {
    if (!people || people.length === 0) return;
    let cancelled = false;
    fetchLabels(requestBody())
      .then((res) => { if (!cancelled) setLabels(res.labels); })
      .catch(() => { /* preview only — the run itself is authoritative */ });
    return () => { cancelled = true; };
  }, [personRoles, personCustomLabels, ignoredPeople, people, requestBody, fetchLabels]);

  const needsInput = useMemo(
    () => (people ?? []).filter(
      (p) => p.confidence === 'unknown' && !personRoles[p.full_name]
             && !ignoredPeople.includes(p.full_name),
    ).length,
    [people, personRoles, ignoredPeople],
  );

  // Unknowns first — the ones actually needing attention lead.
  const ordered = useMemo(() => {
    const rank = (p: PersonInfo) =>
      personRoles[p.full_name] || ignoredPeople.includes(p.full_name) ? 2
        : p.confidence === 'unknown' ? 0 : 1;
    return [...(people ?? [])].sort((a, b) => rank(a) - rank(b));
  }, [people, personRoles, ignoredPeople]);

  // Nobody to classify: skip straight on, guarded so Back doesn't bounce
  // the user forward again (same pattern as ConversionStatus, rule 38).
  useEffect(() => {
    if (loading || people === null || people.length > 0) return;
    const key = `people:${folderPath}:${studentName}`;
    if (peopleAutoSkippedKey === key || skipKey.current === key) return;
    skipKey.current = key;
    setPeopleAutoSkippedKey(key);
    navigateTo('final_confirmation');
  }, [loading, people, folderPath, studentName, peopleAutoSkippedKey,
      setPeopleAutoSkippedKey, navigateTo]);

  if (!detectionResults) return null;

  if (loading) {
    return (
      <div className="py-16 text-center text-sm text-slate-400">
        Working out who&apos;s who…
      </div>
    );
  }

  if (people !== null && people.length === 0) {
    return (
      <div className="py-16 text-center space-y-4">
        <p className="text-sm text-slate-500">
          No people to classify in these documents.
        </p>
        <div className="flex justify-center gap-2">
          <button
            onClick={() => navigateTo('document_review')}
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-100 border border-slate-200 transition-colors btn-press"
          >
            <ArrowLeft size={16} /> Back
          </button>
          <button
            onClick={() => navigateTo('final_confirmation')}
            className="flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium bg-primary-600 text-white hover:bg-primary-700 transition-all btn-press"
          >
            Continue <ArrowRight size={16} />
          </button>
        </div>
      </div>
    );
  }

  const currentValue = (p: PersonInfo) => {
    if (ignoredPeople.includes(p.full_name)) return IGNORE;
    if (personCustomLabels[p.full_name] || customOpen[p.full_name]) return CUSTOM;
    return personRoles[p.full_name] || p.suggested_role;
  };

  const reason = (p: PersonInfo) => {
    if (p.source === 'entered') return 'You entered this name yourself.';
    if (p.confidence === 'unknown') return "Not enough context to tell — please choose.";
    const what = roleOptions.find((r) => r.key === p.suggested_role)?.label
      ?? p.suggested_role;
    return `Looks like ${what.toLowerCase()} — "${p.evidence}" appears nearby.`;
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold text-slate-800 tracking-tight">
          Who&apos;s who?
        </h2>
        <p className="text-sm text-slate-400 mt-1">
          {needsInput > 0
            ? `${needsInput} of ${people?.length} need your input.`
            : 'Check these look right, then continue.'}
        </p>
      </div>

      <div className="flex items-start gap-3 bg-slate-50 border border-slate-200 rounded-lg px-4 py-3">
        <HelpCircle size={18} className="text-slate-400 shrink-0 mt-0.5" />
        <p className="text-sm text-slate-500">
          Telling the AI that someone is a teacher rather than a paediatrician
          changes how it reads their comments. Where we can&apos;t tell, we leave it
          as <span className="font-medium">Other person</span> rather than guess.
          A specific role is more useful but a little more identifying — use a
          general one if you&apos;re unsure.
        </p>
      </div>

      <div className="space-y-2">
        {ordered.map((p) => {
          const value = currentValue(p);
          const answered = Boolean(personRoles[p.full_name])
            || ignoredPeople.includes(p.full_name);
          const ignored = ignoredPeople.includes(p.full_name);

          return (
            <motion.div
              key={p.full_name}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              className={`bg-white rounded-xl border p-4 ${
                answered ? 'border-emerald-200' : 'border-slate-200'
              }`}
            >
              <div className="flex items-start gap-3">
                <UserRound size={18} className="text-slate-300 shrink-0 mt-0.5" />

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-slate-700">{p.full_name}</span>
                    <span className="text-[11px] text-slate-400">
                      {p.occurrences} mention{p.occurrences === 1 ? '' : 's'}
                    </span>
                    {answered && <Check size={13} className="text-emerald-500" />}
                  </div>

                  <p className="text-xs text-slate-400 mt-1">{reason(p)}</p>

                  {p.snippet && (
                    <p className="text-[11px] text-slate-400 mt-1.5 italic border-l-2 border-slate-100 pl-2">
                      {p.snippet.length > 140 ? `${p.snippet.slice(0, 140)}…` : p.snippet}
                    </p>
                  )}

                  <div className="flex items-center gap-2 mt-3 flex-wrap">
                    <select
                      value={value}
                      onChange={(e) => {
                        const v = e.target.value;
                        if (v === IGNORE) {
                          setPersonIgnored(p.full_name, true);
                          setCustomOpen({ ...customOpen, [p.full_name]: false });
                        } else if (v === CUSTOM) {
                          setCustomOpen({ ...customOpen, [p.full_name]: true });
                        } else {
                          setCustomOpen({ ...customOpen, [p.full_name]: false });
                          setPersonRole(p.full_name, v);
                        }
                      }}
                      className="px-3 py-1.5 rounded-lg border border-slate-200 text-sm text-slate-600
                                 focus:outline-none focus:ring-2 focus:ring-primary-200"
                    >
                      {roleOptions.map((r) => (
                        <option key={r.key} value={r.key}>{r.label}</option>
                      ))}
                      <option value={CUSTOM}>Something else…</option>
                      <option value={IGNORE}>Not a person — ignore</option>
                    </select>

                    {value === CUSTOM && (
                      <input
                        type="text"
                        placeholder="e.g. Speech pathologist"
                        defaultValue={personCustomLabels[p.full_name] ?? ''}
                        maxLength={30}
                        onBlur={(e) =>
                          setPersonRole(p.full_name, personRoles[p.full_name] || 'other',
                                        e.target.value.trim())}
                        className="px-3 py-1.5 rounded-lg border border-slate-200 text-sm
                                   focus:outline-none focus:ring-2 focus:ring-primary-200"
                      />
                    )}

                    <span className="text-xs text-slate-400">→</span>
                    <code className={`text-xs px-2 py-1 rounded ${
                      ignored ? 'bg-slate-100 text-slate-400' : 'bg-primary-50 text-primary-600'
                    }`}>
                      {ignored ? 'not treated as a name' : labels[p.full_name] ?? p.label}
                    </code>
                  </div>
                </div>
              </div>
            </motion.div>
          );
        })}
      </div>

      <div className="flex justify-between items-center pt-2">
        <button
          onClick={() => navigateTo('document_review')}
          className="flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm text-slate-600 hover:bg-slate-100 transition-colors btn-press"
        >
          <ArrowLeft size={16} /> Back
        </button>

        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              // What the dropdowns SHOW is what the run uses — commit it.
              acceptSuggestedRoles(
                effectiveRoleMap(people ?? [], personRoles, ignoredPeople)
              );
              navigateTo('final_confirmation');
            }}
            className="flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium
                       bg-primary-600 text-white hover:bg-primary-700 shadow-sm hover:shadow
                       transition-all btn-press"
          >
            Continue <ArrowRight size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}
