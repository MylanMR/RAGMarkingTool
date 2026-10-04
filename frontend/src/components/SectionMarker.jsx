import React from 'react';
import {
  LEVELS,
  LEVEL_LABELS,
  CAVEATS,
  composeMarking,
  levelStyle,
} from '../marking.js';

// Section-level marking UI. The classification select starts empty and there
// is no default: until a level is chosen the section shows UNMARKED and the
// parent form refuses to submit. The IC caveat is a second dropdown; picking
// REL TO reveals a country-code field, and the marking stays incomplete
// until the codes are entered.
export default function SectionMarker({ section, index, onChange, onRemove, canRemove }) {
  const marking = composeMarking(section);
  const set = (patch) => onChange(index, { ...section, ...patch });

  const caveatDisabled = !section.level || section.level === 'U';
  const relToPending = section.caveat === 'REL TO' && !(section.relTo || '').trim();

  return (
    <fieldset className="section-marker">
      <legend>
        Section {index + 1}
        {marking ? (
          <span className="marking-chip" style={levelStyle(section.level)}>
            {marking}
          </span>
        ) : (
          <span className="marking-chip unmarked">
            {relToPending
              ? 'INCOMPLETE — REL TO needs country codes'
              : 'UNMARKED — marking required'}
          </span>
        )}
      </legend>

      <div className="row">
        <label>
          Heading (optional)
          <input
            type="text"
            value={section.heading}
            onChange={(e) => set({ heading: e.target.value })}
            placeholder="e.g. Findings"
          />
        </label>
        <label>
          Program / SAP (optional)
          <input
            type="text"
            value={section.program}
            onChange={(e) => set({ program: e.target.value })}
            placeholder="e.g. ALPHA"
          />
        </label>
      </div>

      <label>
        Content
        <textarea
          required
          rows={4}
          value={section.content}
          onChange={(e) => set({ content: e.target.value })}
          placeholder="Section text…"
        />
      </label>

      <div className="marking-controls">
        <label>
          Classification
          <select
            required
            value={section.level}
            onChange={(e) => {
              const level = e.target.value;
              // Dropping to U clears the caveat; U portions carry none.
              if (level === 'U') {
                set({ level, caveat: '', relTo: '' });
              } else {
                set({ level });
              }
            }}
          >
            <option value="" disabled>
              — select (required) —
            </option>
            {LEVELS.map((lv) => (
              <option key={lv} value={lv}>
                {lv} — {LEVEL_LABELS[lv]}
              </option>
            ))}
          </select>
        </label>

        <label>
          IC Caveat
          <select
            disabled={caveatDisabled}
            value={section.caveat}
            onChange={(e) => {
              const caveat = e.target.value;
              set({ caveat, relTo: caveat === 'REL TO' ? section.relTo : '' });
            }}
            title={
              caveatDisabled && section.level === 'U'
                ? 'Unclassified portions carry no caveats'
                : undefined
            }
          >
            <option value="">— none —</option>
            {CAVEATS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>

        {section.caveat === 'REL TO' && (
          <label>
            Country codes (trigraphs, comma-separated)
            <input
              type="text"
              required
              value={section.relTo}
              onChange={(e) => set({ relTo: e.target.value })}
              placeholder="USA, GBR"
            />
          </label>
        )}
      </div>

      {canRemove && (
        <button type="button" className="link danger" onClick={() => onRemove(index)}>
          Remove section
        </button>
      )}
    </fieldset>
  );
}
