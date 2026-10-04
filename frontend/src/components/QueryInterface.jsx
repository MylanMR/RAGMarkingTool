import React, { useState } from 'react';
import { runQuery } from '../api.js';
import { levelStyle } from '../marking.js';

// Search uses the signed-in identity's attributes. Results are already
// filtered by the policy decision point and every query is audited.
export default function QueryInterface() {
  const [query, setQuery] = useState('');
  const [topK, setTopK] = useState(8);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError(null); setResult(null);
    try { setResult(await runQuery({ query: query.trim(), top_k: Number(topK) })); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }

  return (
    <div className="panel">
      <h2>Search holdings</h2>
      <form onSubmit={submit}>
        <div className="row">
          <label className="grow">Query<input value={query} onChange={(e) => setQuery(e.target.value)} /></label>
          <label className="narrow-field">Results
            <select value={topK} onChange={(e) => setTopK(e.target.value)}>{[4, 8, 12, 20].map((n) => <option key={n} value={n}>{n}</option>)}</select>
          </label>
          <button disabled={busy || !query.trim()}>{busy ? 'Searching' : 'Search'}</button>
        </div>
      </form>
      {error && <p className="error">{error}</p>}
      {result && (
        <>
          <p className="muted">{result.hits.length} result(s). Audit entry {result.audit_id}.</p>
          {result.hits.map((h) => (
            <div key={h.chunk_id} className="hit">
              <div className="hit-banner" style={levelStyle(h.classification)}>{h.portion_marking}</div>
              <p>{h.content}</p>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
