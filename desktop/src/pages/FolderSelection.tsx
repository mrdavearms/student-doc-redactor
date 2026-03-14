import { useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import { FolderOpen, User, Users, Building, ArrowRight, Search } from 'lucide-react';
import { useStore } from '../store';
import { api } from '../api';
import HelpTip from '../components/HelpTip';

export default function FolderSelection() {
  const {
    folderPath, studentName, parentNames, familyNames,
    organisationNames, redactHeaderFooter, folderValid,
    setFolderPath, setStudentName, setParentNames, setFamilyNames,
    setOrganisationNames, setRedactHeaderFooter, setFolderValid, navigateTo,
  } = useStore();

  const [validating, setValidating] = useState(false);

  const validateFolder = useCallback(async (path: string) => {
    setFolderPath(path);
    if (!path.trim()) {
      setFolderValid(false);
      return;
    }
    setValidating(true);
    try {
      const res = await api.validateFolder(path.trim());
      setFolderValid(res.exists && res.is_directory);
    } catch {
      setFolderValid(false);
    } finally {
      setValidating(false);
    }
  }, [setFolderPath, setFolderValid]);

  const handleBrowse = useCallback(async () => {
    const selected = await window.electronAPI?.selectFolder();
    if (selected) {
      validateFolder(selected);
    }
  }, [validateFolder]);

  const canProceed = folderValid && studentName.trim().length > 0;

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-800 tracking-tight">Select Folder & Student Details</h2>
        <p className="text-sm text-slate-400 mt-1">Choose the folder containing student documents and enter identifying information.</p>
      </div>

      {/* Folder selection */}
      <motion.section
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.05 }}
        className="bg-white rounded-xl border border-slate-200 p-6 space-y-4"
      >
        <div className="flex items-center gap-2 text-slate-700 font-medium">
          <FolderOpen size={18} className="text-primary-500" />
          Input Folder
        </div>

        <div className="flex gap-2">
          <input
            type="text"
            value={folderPath}
            onChange={(e) => validateFolder(e.target.value)}
            placeholder="/Users/username/Documents/Student_Docs"
            className={`
              flex-1 px-4 py-2.5 rounded-lg border text-sm transition-colors
              focus:outline-none focus:ring-2 focus:ring-primary-200 focus:border-primary-400
              ${folderValid ? 'border-emerald-300 bg-emerald-50/50' : folderPath ? 'border-red-300 bg-red-50/30' : 'border-slate-200'}
            `}
          />
          <button
            type="button"
            onClick={handleBrowse}
            className="flex items-center gap-1.5 px-4 py-2.5 rounded-lg border border-slate-200 bg-slate-50
                       text-sm text-slate-600 font-medium hover:bg-slate-100 hover:border-slate-300
                       transition-colors shrink-0 btn-press"
          >
            <Search size={14} />
            Browse
          </button>
        </div>

        {validating && <p className="text-xs text-slate-400">Checking folder...</p>}
        {!validating && folderPath && folderValid && (
          <p className="text-xs text-emerald-600">Folder found</p>
        )}
        {!validating && folderPath && !folderValid && (
          <p className="text-xs text-red-500">Folder not found — check the path</p>
        )}
      </motion.section>

      {/* Student details */}
      <motion.section
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="bg-white rounded-xl border border-slate-200 p-6 space-y-5"
      >
        <div className="flex items-center gap-2 text-slate-700 font-medium">
          <User size={18} className="text-primary-500" />
          Student Information
        </div>

        <div>
          <label className="flex items-center gap-1.5 text-sm text-slate-600 mb-1.5">
            Student full name <span className="text-red-400">*</span>
            <HelpTip text="Enter the student's full name as it appears in their documents. First and last name. The tool will also detect variations like first-name-only and surname-only." />
          </label>
          <input
            type="text"
            value={studentName}
            onChange={(e) => setStudentName(e.target.value)}
            placeholder="e.g., John Smith"
            className="w-full px-4 py-2.5 rounded-lg border border-slate-200 text-sm
                       focus:outline-none focus:ring-2 focus:ring-primary-200 focus:border-primary-400"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="flex items-center gap-1.5 text-sm text-slate-600 mb-1.5">
              <Users size={14} className="text-slate-400" />
              Parent/Guardian names
              <HelpTip text="Include anyone whose name might appear in the documents — referral letters, consent forms, and reports often mention parents by name." />
            </label>
            <input
              type="text"
              value={parentNames}
              onChange={(e) => setParentNames(e.target.value)}
              placeholder="Jane Smith, Robert Smith"
              className="w-full px-4 py-2.5 rounded-lg border border-slate-200 text-sm
                         focus:outline-none focus:ring-2 focus:ring-primary-200 focus:border-primary-400"
            />
            <p className="text-[11px] text-slate-400 mt-1">Optional, comma-separated</p>
          </div>

          <div>
            <label className="flex items-center gap-1.5 text-sm text-slate-600 mb-1.5">
              <Users size={14} className="text-slate-400" />
              Other family members
              <HelpTip text="Siblings or other family members sometimes appear in assessment reports, especially in background history sections." />
            </label>
            <input
              type="text"
              value={familyNames}
              onChange={(e) => setFamilyNames(e.target.value)}
              placeholder="Emma Smith, Tom Smith"
              className="w-full px-4 py-2.5 rounded-lg border border-slate-200 text-sm
                         focus:outline-none focus:ring-2 focus:ring-primary-200 focus:border-primary-400"
            />
            <p className="text-[11px] text-slate-400 mt-1">Optional, comma-separated</p>
          </div>
        </div>

        <div>
          <label className="flex items-center gap-1.5 text-sm text-slate-600 mb-1.5">
            <Building size={14} className="text-slate-400" />
            Organisation names
            <HelpTip text="Schools, clinics, hospitals, therapy centres — any organisation name that could identify the student's location or service providers." />
          </label>
          <input
            type="text"
            value={organisationNames}
            onChange={(e) => setOrganisationNames(e.target.value)}
            placeholder="Sunrise Primary School, City Paediatrics"
            className="w-full px-4 py-2.5 rounded-lg border border-slate-200 text-sm
                       focus:outline-none focus:ring-2 focus:ring-primary-200 focus:border-primary-400"
          />
          <p className="text-[11px] text-slate-400 mt-1">Optional, comma-separated — schools, clinics, etc.</p>
        </div>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={redactHeaderFooter}
            onChange={(e) => setRedactHeaderFooter(e.target.checked)}
            className="w-4 h-4 rounded border-slate-300 text-primary-600
                       focus:ring-primary-200 focus:ring-offset-0"
          />
          <span className="text-sm text-slate-600 flex items-center gap-1.5">
            Redact headers & footers (blanks top/bottom of every page — removes letterheads and addresses)
            <HelpTip text="Blanks the top and bottom of every page. Useful for removing school letterheads, clinic logos, and addresses that appear in page margins." />
          </span>
        </label>
      </motion.section>

      {/* Warning + proceed */}
      {!canProceed && (
        <p className="text-sm text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-4 py-2.5">
          Please select a valid folder and enter the student's name to continue.
        </p>
      )}

      <div className="flex justify-end">
        <button
          disabled={!canProceed}
          onClick={() => navigateTo('conversion_status')}
          className={`
            flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium transition-all
            ${canProceed
              ? 'bg-primary-600 text-white hover:bg-primary-700 shadow-sm hover:shadow btn-press'
              : 'bg-slate-100 text-slate-300 cursor-not-allowed'
            }
          `}
        >
          Start Processing <ArrowRight size={16} />
        </button>
      </div>
    </div>
  );
}
