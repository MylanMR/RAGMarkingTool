// Marking helpers shared by the intake and query UIs.
// Mirrors backend/models/marking.py: levels U < C < S < TS; controls
// NF/NOFORN, OC/ORCON, REL TO CCC[, CCC...]; NOFORN and REL TO are mutually
// exclusive; U portions carry no controls. The backend re-validates
// everything — this module only drives the form UX.

export const LEVELS = ['U', 'C', 'S', 'TS', 'TS/SCI'];

export const LEVEL_RANK = { U: 0, C: 1, S: 2, TS: 3, 'TS/SCI': 4 };

export const LEVEL_LABELS = {
  U: 'UNCLASSIFIED',
  C: 'CONFIDENTIAL',
  S: 'SECRET',
  TS: 'TOP SECRET',
  'TS/SCI': 'TOP SECRET//SCI',
};

// Standard banner colors. TS/SCI uses the yellow SCI banner, which needs
// dark text — always pair LEVEL_COLORS with LEVEL_TEXT_COLORS.
export const LEVEL_COLORS = {
  U: '#007a33',
  C: '#0033a0',
  S: '#c8102e',
  TS: '#ff8c00',
  'TS/SCI': '#fce83a',
};

export const LEVEL_TEXT_COLORS = {
  U: '#ffffff',
  C: '#ffffff',
  S: '#ffffff',
  TS: '#ffffff',
  'TS/SCI': '#1c1e21',
};

export function levelStyle(level) {
  return {
    backgroundColor: LEVEL_COLORS[level],
    color: LEVEL_TEXT_COLORS[level] || '#ffffff',
  };
}

// IC caveats offered in the caveat dropdown. 'REL TO' additionally needs
// country trigraphs supplied by the user.
export const CAVEATS = ['NOFORN', 'REL TO', 'ORCON', 'PROPIN', 'RELIDO', 'NOCON'];

export function dominates(a, b) {
  return LEVEL_RANK[a] >= LEVEL_RANK[b];
}

// Compose a portion-marking string from form state, or null if the marking
// is incomplete (no level chosen, or REL TO selected without country codes).
// There is deliberately no fallback level: an unmarked section stays
// unmarked and blocks submission.
export function composeMarking({ level, caveat, relTo }) {
  if (!level || !LEVELS.includes(level)) return null;
  if (level === 'U' || !caveat) return `(${level})`;
  if (caveat === 'REL TO') {
    const rel = (relTo || '').trim().toUpperCase();
    if (!rel) return null; // REL TO needs country codes before it's a marking
    return `(${level}//REL TO ${rel})`;
  }
  return `(${level}//${caveat})`;
}

// Split a comma-separated list into trimmed, non-empty entries.
export function parseList(text) {
  return (text || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}
