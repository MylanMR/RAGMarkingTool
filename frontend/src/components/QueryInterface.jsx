import React, { useState } from 'react';
import { runQuery } from '../api.js';
import { LEVELS, LEVEL_LABELS, levelStyle, parseList } from '../marking.js';

// Query UI. SCAFFOLDING ONLY: user attributes are typed into the form so the
// pipeline can be exercised. Production derives them from the authenticated
// identity (PKI/IdP), never from the client.
export default function QueryInterface() {
  const [userId, setUserId] = useState('');
  const [clearance, setClearance] = useState(''); // no default
  const [citizenship, setCitizenship] = useState('');
  const [compartments, setCompartments] = useState('');
  const [ntkGroups, setNtkGroups] = useState('');
  const [query, setQuery] = useState('');
  const [topK, setTopK] = useState(8);

  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const canRun =
    !running &&
    userId.trim() &&
    clearance &&
    /^[A-Za-z]{3}$/.test(citizenship.trim()) &&
    query.trim();

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    setResult(null);
    setRunning(true);
    try {
      const body = await runQuery({
        query: query.trim(),
        top_k: Number(topK),
        user: {
          user_id: userId.trim(),
          clearance,
          citizenship: citizenship.trim().toUpperCase(),
          compartments: parseList(compartments),
          need_to_know_groups: parseList(ntkGroups),
        },
      });
      setResult(body);
    } catch (err) {
      setError(err.message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="panel">
      <h2>Query</h2>
      <p className="hint warn">
        Scaffolding auth: attributes entered here are sent with the request. In
        production they come from the authenticated identity, not this form.
      </p>

      <form onSubmit={handleSubmit}>
        <div className="row">
          <label>
            User ID
            <input
              type="text"
              required
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
            />
          </label>
          <label>
            Clearance
            <select
              required
              value={clearance}
              onChange={(e) => setClearance(e.target.value)}
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
            Citizenship (trigraph)
            <input
              type="text"
              required
              maxLength={3}
              value={citizenship}
              onChange={(e) => setCitizenship(e.target.value)}
              placeholder="USA"
            />
          </label>
        </div>

        <div className="row">
          <label>
            Compartments (comma-separated)
            <input
              type="text"
              value={compartments}
              onChange={(e) => setCompartments(e.target.value)}
              placeholder="ALPHA, BRAVO"
            />
          </label>
          <label>
            Need-to-know groups (comma-separated)
            <input
              type="text"
              value={ntkGroups}
              onChange={(e) => setNtkGroups(e.target.value)}
              placeholder="ORCON"
            />
          </label>
          <label>
            Top K
            <input
              type="number"
              min={1}
              max={50}
              value={topK}
              onChange={(e) => setTopK(e.target.value)}
            />
          </label>
        </div>

        <label>
          Query
          <textarea
            required
            rows={2}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="What are you looking for?"
          />
        </label>

        <button type="submit" disabled={!canRun}>
          {running ? 'Searching…' : 'Run filtered search'}
        </button>
      </form>

      {error && <div className="error">{error}</div>}

      {result && (
        <div className="result">
          <h3>
            {result.hits.length} authorized chunk
            {result.hits.length === 1 ? '' : 's'}
          </h3>
          <p className="hint">
            Filter applied in-query — levels:{' '}
            {result.filter_summary.allowed_levels.join(', ') || 'none'}; permitted
            controls: {result.filter_summary.permitted_controls.join(', ') || 'none'};
            programs: {result.filter_summary.allowed_programs.join(', ') || 'none'}.
            Audit entry <code>{result.audit_id}</code>.
          </p>

          {result.hits.length === 0 && (
            <p>No chunks in the store are authorized for these attributes.</p>
          )}

          {result.hits.map((hit) => (
            <div className="hit" key={hit.chunk_id}>
              <div className="hit-banner" style={levelStyle(hit.classification)}>
                {hit.portion_marking}
                {hit.program ? ` · PROGRAM ${hit.program}` : ''}
                <span className="score">score {hit.score.toFixed(3)}</span>
              </div>
              <p className="hit-content">{hit.content}</p>
              <p className="hit-meta">
                chunk <code>{hit.chunk_id.slice(0, 8)}</code> · doc{' '}
                <code>{hit.parent_doc_id.slice(0, 8)}</code>
              </p>
            </div>
          ))}

          {result.decisions.length > 0 && (
            <details>
              <summary>PDP decisions ({result.decisions.length})</summary>
              <ul className="decision-list">
                {result.decisions.map((d) => (
                  <li key={d.chunk_id}>
                    <code>{d.chunk_id.slice(0, 8)}</code> — {d.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
