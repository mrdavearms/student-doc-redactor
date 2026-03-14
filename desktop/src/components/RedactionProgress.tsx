import { useState, useEffect, useRef, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ShieldCheck } from 'lucide-react';

/**
 * Teacher-themed witty comments that cycle during redaction.
 * Shuffled on each mount so repeat runs feel fresh.
 */
const WITTY_COMMENTS = [
  'Policying it up...',
  'Compliancing...',
  'AIPing...',
  'FormFillering...',
  'Risk Assessing...',
  'VRQAing...',
  'School Counciling...',
  'Strategic Planning...',
  'Emergency Managing...',
  'Anaphylaxis Checking...',
  'Consulting the Oracle...',
  'Reviewing Mandatories...',
  'Brewing a fresh pot of pedagogy...',
  'Aligning the pedagogical planets...',
  'Warming up the servers with some strong coffee.',
  "Dusting off the ol' instructional model.",
  'Synthesising synergy and other important-sounding buzzwords.',
  'Running this through the staff meeting simulator...',
  'Checking for split infinitives...',
  'Finding the perfect meme for the all-staff email...',
  'How about you go and check there is paper in the photocopier?',
  'Have you washed your coffee cup recently?',
  'Give your desk a quick cleanup.',
  'Write a warm fuzzy for a colleague.',
  'Time for a bit of yoga.',
  'Go on, read the staff bulletin. It will make you a better person!',
  'Cross-checking with the staffroom gossip network.',
  'Quietly reminding the AI that recess duty is non-negotiable.',
  'Searching for that elusive missing whiteboard marker.',
  'Taking attendance of stray learning outcomes.',
  'Applying just enough rigour to scare off mediocrity.',
  'FISO-ing for facts...',
  'Checking the Dimensions of the Framework.',
  "Consulting the Knowledge Bank (and hoping it's not overdrawn).",
  "Translating 'Blue Sky Thinking' into a Budget Line Item.",
  'Searching for the owner of the unlabeled Tupperware in the fridge.',
  "Validating that 'per my last email' was sufficiently passive-aggressive.",
  'Evacuating the AI to the oval for an unannounced drill.',
  'Laminating the search results for longevity.',
  "Attempting to bypass the 'Reply All' storm.",
  "Calculating the exact duration of a 'quick' corridor conversation.",
  'Checking if the excursion bus is actually booked.',
  "Synthesising the feedback from the 3:45 PM 'briefing'.",
  'Checking the yard duty roster. Is it you? It might be you.',
  'Go grab a glue stick. You can never have too many glue sticks.',
  'Peer-reviewing the HITS (High Impact Teaching Strategies).',
  "Sifting through the 'Not Applicable' columns of the spreadsheets.",
  'Escalating this query to the Regional Office (mentally).',
  'Confiscating a digital fidget spinner.',
  "Chasing the elusive 'lost property' hoodie.",
  "Wait — is that the bell, or just my tinnitus?",
  "Bargaining for a spare period that doesn't exist.",
  "Wondering why there are 47 open tabs on this 'Teacher Laptop'.",
  'Drafting a 15-page brief for a 2-minute decision.',
  "Consulting the 'Way We Work' document for a vibe check.",
  "Aligning our synergies with the Secretary's vision.",
  "Checking if we have enough 'Evidence-Based' glitter for this project.",
  "Converting 'I don't know' into 'That is a great question for the working group'.",
  'Quick! Go hide in the staff room before someone asks you to cover a class.',
  "Go check the pigeonholes. There's probably a physical memo from 2004 in there.",
  'Is it a Professional Practice Day yet? Asking for a friend.',
  'Checking the price of a small coffee at the local cafe (for moral support).',
  "Rescuing a stray 'Success Criterion' from the hallway.",
  'Applying for a grant to finish this search faster.',
  "Checking if the communal milk is past its 'best before' date.",
  "Validating that your 'Work-Life Balance' still exists (searching...).",
  "Drafting a 'Notice of Concern' for the slow server speed.",
  "Checking if there's any leftover cake in the front office.",
  "Optimising for 'Differentiated Learning' (and differentiated snacks).",
  'Recalculating the yard duty swap you owe your colleague.',
  "Looking for a whiteboard marker that isn't actually a permanent one.",
  "Checking the 'Compass' notifications... oh no, there's 507.",
  "Ensuring the 'Differentiation' isn't just a different colored font.",
  'Seeking approval from the Treasury Place gods.',
  "Determining if this search counts as 'Continuing Professional Development'.",
  "Scanning for any mention of 'NAPLAN' and muting it.",
  'Trying to remember your password for the fifth time this week.',
  "Verifying that the 'Fruit Box' in the staffroom isn't just empty peels.",
  'Checking if the printer has finally decided to retire.',
  "It's 46 degrees outside. I'll set the aircon to 15 and hope I can bring the classroom to 39 by lunch.",
  "Measuring the 'Learning Growth' of this progress bar.",
  "Updating the 'Risk Register' to include 'Running out of Coffee'.",
  "Ensuring this search doesn't violate any 'Local Agreements'.",
  "Assessing the 'Student Voice' (it's currently very loud in the corridor).",
  "Searching for that one USB stick you haven't seen since 2019.",
];

/** Fisher-Yates shuffle */
function shuffle<T>(arr: T[]): T[] {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

interface RedactionProgressProps {
  totalDocuments: number;
}

export default function RedactionProgress({ totalDocuments }: RedactionProgressProps) {
  const [commentIndex, setCommentIndex] = useState(0);
  const [progress, setProgress] = useState(0);
  const startTime = useRef(Date.now());

  // Shuffle comments once on mount so repeat runs feel different
  const shuffledComments = useMemo(() => shuffle(WITTY_COMMENTS), []);

  // Cycle through comments every 3.5 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      setCommentIndex((i) => (i + 1) % shuffledComments.length);
    }, 3500);
    return () => clearInterval(interval);
  }, [shuffledComments.length]);

  // Fake progress that moves quickly to ~30%, then slows to ~85% over time
  // This gives the feeling of real progress without actual backend feedback
  useEffect(() => {
    const interval = setInterval(() => {
      const elapsed = (Date.now() - startTime.current) / 1000;
      // Logarithmic curve: fast start, slow approach to 90%
      // Each document takes ~3-8 seconds on average
      const estimatedSeconds = totalDocuments * 5;
      const fraction = elapsed / estimatedSeconds;
      const newProgress = Math.min(90, Math.round(fraction * 100 * (1 - fraction * 0.3)));
      setProgress((prev) => Math.max(prev, newProgress));
    }, 200);
    return () => clearInterval(interval);
  }, [totalDocuments]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-8"
    >
      {/* Header */}
      <div className="text-center">
        <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-primary-50 mb-4">
          <motion.div
            animate={{ rotate: [0, 10, -10, 0] }}
            transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
          >
            <ShieldCheck size={28} className="text-primary-600" />
          </motion.div>
        </div>
        <h2 className="text-2xl font-bold text-slate-800 tracking-tight">Redacting Documents</h2>
        <p className="text-sm text-slate-400 mt-1">
          Processing {totalDocuments} document{totalDocuments === 1 ? '' : 's'}...
        </p>
      </div>

      {/* Progress bar */}
      <div className="max-w-md mx-auto space-y-2">
        <div className="h-2.5 bg-slate-100 rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-gradient-to-r from-primary-500 to-primary-400 rounded-full"
            initial={{ width: '0%' }}
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.5, ease: 'easeOut' }}
          />
        </div>
        <div className="flex justify-between text-xs text-slate-400">
          <span>Redacting PII...</span>
          <span>{progress}%</span>
        </div>
      </div>

      {/* Witty comment — animated swap */}
      <div className="max-w-md mx-auto text-center min-h-[48px] flex items-center justify-center">
        <AnimatePresence mode="wait">
          <motion.p
            key={commentIndex}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.3 }}
            className="text-sm text-slate-500 italic leading-relaxed"
          >
            {shuffledComments[commentIndex]}
          </motion.p>
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
