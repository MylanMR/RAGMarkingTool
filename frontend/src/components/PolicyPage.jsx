import React, { useEffect, useMemo, useState } from 'react';
import { getPolicy, policyHistory, putPolicy } from '../api.js';
import { levelStyle } from '../marking.js';

// AO risk policy. Every control is a closed drop-down; the risk statement for
// the selected option is shown beside it. Choosing a less strict option than
// the saved one is a relaxation and requires a written justification.
export default function PolicyPage({ user }) {
  const isAO = user.roles.includes('ao');
  const [data, setData] = useState(null);
  const [draft, setDraft] = useState(null);
  const [justification, setJustification] = useState('');
  const [history, setHistory] = useState([]);
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);

  async function load() {
    const p = await getPolicy();
    setData(p);
    setDraft(JSON.parse(JSON.stringify(p.settings)));
    if (isAO || user.roles.includes('auditor') || user.roles.includes('admin')) {
      setHistory(await policyHistory());
    }
  }
  useEffect(() => { load().catch((e) => setError(e.message)); }, []);

  const relaxed = useMemo(() => {
    if (!data || !draft) return [];
    const out = [];
    for (const s of data.catalog) {
      const rank = (v) => s.options.find((o) => o.value === v).strictness;
      if (s.scope === 'per_level') {
        for (const lv of s.levels) {
          if (rank(draft[s.key][lv]) < rank(data.settings[s.key][lv])) out.push(`${s.label} (${lv})`);
        }
      } else if (rank(draft[s.key]) < rank(data.settings[s.key])) out.push(s.label);
    }
    return out;
  }, [data, draft]);

  if (error && !data) return <div className="panel"><p className="error">{error}</p></div>;
  if (!data || !draft) return <div className="panel">Loading policy</div>;

  const dirty = JSON.stringify(draft) !== JSON.stringify(data.settings);
  const needJust = relaxed.length > 0 && justification.trim().length < data.min_justification;
  const perLevel = data.catalog.filter((s) => s.scope === 'per_level');
  const groups = [...new Set(data.catalog.filter((s) => s.scope === 'global').map((s) => s.group))];
  const setVal = (key, lv, v) => setDraft((d) => {
    const n = JSON.parse(JSON.stringify(d));
    if (lv) n[key][lv] = v; else n[key] = v;
    return n;
  });

  async function save() {
    setError(null);
    setMsg(null);
    try {
      await putPolicy(draft, justification.trim() || null);
      setJustification('');
      await load();
      setMsg('Policy saved and recorded in the governance log.');
    } catch (e) { setError(e.message); }
  }

  return (
    <div className="panel">
      <h2>Risk policy <span className="muted">version {data.version}</span></h2>
      <p className="hint">
        {isAO ? 'Select an option for each control. Changes take effect for products submitted after you save; products already in review keep the policy they were submitted under.'
          : 'Read only. Only an Authorizing Official can change these settings.'}
      </p>

      <h3>Release controls by classification</h3>
      <div className="table-scroll">
        <table className="policy-table">
          <thead>
            <tr><th>Control</th>{perLevel[0].levels.map((lv) => (
              <th key={lv}><span className="marking-chip" style={levelStyle(lv)}>{lv}</span></th>))}</tr>
          </thead>
          <tbody>
            {perLevel.map((s) => (
              <tr key={s.key}>
                <th scope="row">{s.label}<div className="muted small-text">{s.help}</div></th>
                {s.levels.map((lv) => {
                  const changed = draft[s.key][lv] !== data.settings[s.key][lv];
                  return (
                    <td key={lv} className={changed ? 'changed' : ''}>
                      <select aria-label={`${s.label} for ${lv}`} disabled={!isAO} value={draft[s.key][lv]}
                        onChange={(e) => setVal(s.key, lv, e.target.value)}>
                        {s.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                      </select>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <details className="risk-notes">
        <summary>What each option accepts</summary>
        {perLevel.map((s) => (
          <div key={s.key}><strong>{s.label}</strong>
            <ul>{s.options.map((o) => <li key={o.value}><em>{o.label}.</em> {o.risk}</li>)}</ul>
          </div>
        ))}
      </details>

      {groups.map((g) => (
        <div key={g}>
          <h3>{g}</h3>
          {data.catalog.filter((s) => s.scope === 'global' && s.group === g).map((s) => {
            const opt = s.options.find((o) => o.value === draft[s.key]);
            const changed = draft[s.key] !== data.settings[s.key];
            return (
              <div key={s.key} className={changed ? 'setting changed' : 'setting'}>
                <label>{s.label}
                  <select disabled={!isAO} value={draft[s.key]} onChange={(e) => setVal(s.key, null, e.target.value)}>
                    {s.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </label>
                <p className="muted small-text">{s.help}</p>
                <p className="risk">{opt.risk}</p>
              </div>
            );
          })}
        </div>
      ))}

      <div className="fixed-controls">
        <h3>Always on</h3>
        <p className="muted">These controls are not configurable: the release gate itself, AI-assistance disclosure on every product, fail-closed audit logging, PDP filtering of every retrieval, and the rule that authors never approve or release their own work.</p>
      </div>

      {isAO && dirty && (
        <div className="save-bar">
          {relaxed.length > 0 && (
            <>
              <p className="warn">You are relaxing: {relaxed.join('; ')}. Record why this risk is acceptable.</p>
              <label>Justification (at least {data.min_justification} characters)
                <textarea rows={3} value={justification} onChange={(e) => setJustification(e.target.value)} />
              </label>
            </>
          )}
          <div className="row">
            <button onClick={save} disabled={needJust}>Save policy</button>
            <button className="secondary" onClick={() => { setDraft(JSON.parse(JSON.stringify(data.settings))); setJustification(''); }}>Discard changes</button>
          </div>
        </div>
      )}
      {msg && <p className="ok">{msg}</p>}
      {error && <p className="error">{error}</p>}

      {history.length > 0 && (
        <>
          <h3>History</h3>
          <table className="simple">
            <thead><tr><th>Version</th><th>Changed by</th><th>When</th><th>Relaxed</th><th>Justification</th></tr></thead>
            <tbody>{history.map((h) => (
              <tr key={h.version}><td>{h.version}</td><td>{h.changed_by}</td><td>{new Date(h.changed_at).toLocaleString()}</td>
                <td>{h.relaxed.join(', ') || 'none'}</td><td>{h.justification || ''}</td></tr>))}</tbody>
          </table>
        </>
      )}
    </div>
  );
}
