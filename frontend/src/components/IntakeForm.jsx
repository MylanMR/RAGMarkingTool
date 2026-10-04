import React, { useState } from 'react';
import SectionMarker from './SectionMarker.jsx';
import { ingestDocument, embedDocument } from '../api.js';
import {
  LEVELS,
  LEVEL_LABELS,
  LEVEL_RANK,
  CAVEATS,
  composeMarking,
  dominates,
  levelStyle,
} from '../marking.js';

const emptySection = () => ({
  heading: '',
  content: '',
  level: '', // no default classification, ever
  caveat: '',
  relTo: '',
  program: '',
});

export default function IntakeForm() {
  const [title, setTitle] = useState('');
  const [sourceSystem, setSourceSystem] = useState('');
  const [banner, setBanner] = useState(''); // no default
  const [docCaveat, setDocCaveat] = useState('');
  const [docRelTo, setDocRelTo] = useState('');
  const [program, setProgram] = useState('');
  const [sections, setSections] = useState([emptySection()]);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [embedResult, setEmbedResult] = useState(null);

  const updateSection = (index, next) =>
    setSections((prev) => prev.map((s, i) => (i === index ? next : s)));
  const removeSection = (index) =>
    setSections((prev) => prev.filter((_, i) => i !== index));
  const addSection = () => setSections((prev) => [...prev, emptySection()]);

  const markings = sections.map(composeMarking);
  const allMarked = markings.every(Boolean);
  const allHaveContent = sections.every((s) => s.content.trim().length > 0);

  const markedLevels = sections.filter((s) => s.level).map((s) => s.level);
  const maxSectionLevel = markedLevels.length
    ? markedLevels.reduce((a, b) => (LEVEL_RANK[a] >= LEVEL_RANK[b] ? a : b))
    : null;
  const bannerTooLow =
    banner && maxSectionLevel && !dominates(banner, maxSectionLevel);
  const docRelToPending = docCaveat === 'REL TO' && !docRelTo.trim();

  const canSubmit =
    !submitting &&
    title.trim() &&
    sourceSystem.trim() &&
    banner &&
    allMarked &&
    allHaveContent &&
    !bannerTooLow &&
    !docRelToPending;

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setResult(null);
    setEmbedResult(null);
    setSubmitting(true);
    try {
      const dissem = [];
      if (banner !== 'U' && docCaveat) {
        if (docCaveat === 'REL TO') {
          dissem.push(`REL TO ${docRelTo.trim().toUpperCase()}`);
        } else {
          dissem.push(docCaveat);
        }
      }

      const payload = {
        title: title.trim(),
        source_system: sourceSystem.trim(),
        classification: banner,
        dissem_controls: dissem,
        program: program.trim() || null,
        sections: sections.map((s) => ({
          heading: s.heading.trim() || null,
          content: s.content,
          portion_marking: composeMarking(s),
          program: s.program.trim() || null,
        })),
      };
      const body = await ingestDocument(payload);
      setResult(body);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleEmbed() {
    setError(null);
    setSubmitting(true);
    try {
      setEmbedResult(await embedDocument(result.id));
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="panel" onSubmit={handleSubmit}>
      <h2>Document Intake</h2>
      <p className="hint">
        Every section must carry an explicit portion marking. There are no
        defaults; unmarked sections block submission and the backend rejects
        them independently.
      </p>

      <div className="row">
        <label>
          Title
          <input
            type="text"
            required
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        <label>
          Source system
          <input
            type="text"
            required
            value={sourceSystem}
            onChange={(e) => setSourceSystem(e.target.value)}
            placeholder="e.g. intake-ui"
          />
        </label>
      </div>

      <div className="marking-controls">
        <label>
          Banner classification
          <select
            required
            value={banner}
            onChange={(e) => {
              const lv = e.target.value;
              setBanner(lv);
              if (lv === 'U') {
                setDocCaveat('');
                setDocRelTo('');
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
            disabled={!banner || banner === 'U'}
            value={docCaveat}
            onChange={(e) => {
              const caveat = e.target.value;
              setDocCaveat(caveat);
              if (caveat !== 'REL TO') setDocRelTo('');
            }}
          >
            <option value="">— none —</option>
            {CAVEATS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        {docCaveat === 'REL TO' && (
          <label>
            Country codes (trigraphs, comma-separated)
            <input
              type="text"
              required
              value={docRelTo}
              onChange={(e) => setDocRelTo(e.target.value)}
              placeholder="USA, GBR"
            />
          </label>
        )}
        <label>
          Document program (optional)
          <input
            type="text"
            value={program}
            onChange={(e) => setProgram(e.target.value)}
          />
        </label>
      </div>

      {bannerTooLow && (
        <div className="error">
          Banner classification {banner} does not dominate the highest section
          level {maxSectionLevel}. Raise the banner or lower the section.
        </div>
      )}

      {sections.map((section, i) => (
        <SectionMarker
          key={i}
          section={section}
          index={i}
          onChange={updateSection}
          onRemove={removeSection}
          canRemove={sections.length > 1}
        />
      ))}

      <div className="row">
        <button type="button" className="secondary" onClick={addSection}>
          + Add section
        </button>
        <button type="submit" disabled={!canSubmit}>
          {submitting ? 'Submitting…' : 'Ingest document'}
        </button>
      </div>
      {!allMarked && (
        <p className="hint warn">
          {markings.filter((m) => !m).length} section(s) still unmarked.
        </p>
      )}

      {error && <div className="error">{error}</div>}

      {result && (
        <div className="result">
          <h3>
            Ingested{' '}
            <span className="marking-chip" style={levelStyle(result.classification)}>
              ({result.classification}
              {result.dissem_controls.length
                ? '//' + result.dissem_controls.join('/')
                : ''}
              )
            </span>
          </h3>
          <p>
            Document <code>{result.id}</code> — {result.section_count} sections,{' '}
            {result.chunk_count} chunks, every chunk marked:
          </p>
          <ul className="chunk-list">
            {result.chunks.map((c) => (
              <li key={c.chunk_id}>
                <span
                  className="marking-chip small"
                  style={levelStyle(c.classification)}
                >
                  {c.portion_marking}
                </span>{' '}
                <code>{c.chunk_id.slice(0, 8)}</code> · hash{' '}
                <code>{c.content_hash.slice(0, 12)}…</code>
              </li>
            ))}
          </ul>
          {embedResult ? (
            <p className="success">
              Embedded {embedResult.chunks_embedded} chunks (dim{' '}
              {embedResult.embedding_dim}) into the vector store.
            </p>
          ) : (
            <button type="button" onClick={handleEmbed} disabled={submitting}>
              {submitting ? 'Embedding…' : 'Embed chunks into vector store'}
            </button>
          )}
        </div>
      )}
    </form>
  );
}
