import React, { useState } from 'react';
import { CAVEATS, LEVELS, composeMarking, levelStyle } from '../marking.js';

// Compact portion-marking picker for product claims. Starts empty: there is
// no default level, matching the intake form.
export default function MarkingPicker({ onApply, disabled }) {
  const [m, setM] = useState({ level: '', caveat: '', relTo: '' });
  const marking = composeMarking(m);
  return (
    <span className="marking-picker">
      <select aria-label="Classification" disabled={disabled} value={m.level} onChange={(e) => setM({ ...m, level: e.target.value })}>
        <option value="">Level</option>
        {LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
      </select>
      <select aria-label="Caveat" disabled={disabled || !m.level || m.level === 'U'} value={m.caveat} onChange={(e) => setM({ ...m, caveat: e.target.value })}>
        <option value="">No caveat</option>
        {CAVEATS.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      {m.caveat === 'REL TO' && (
        <input aria-label="REL TO countries" className="rel-input" placeholder="USA, GBR" value={m.relTo} onChange={(e) => setM({ ...m, relTo: e.target.value })} />
      )}
      <button className="small" disabled={disabled || !marking} onClick={() => onApply(marking)}>
        {marking ? <>Apply <span className="marking-chip" style={levelStyle(m.level)}>{marking}</span></> : 'Apply'}
      </button>
    </span>
  );
}
