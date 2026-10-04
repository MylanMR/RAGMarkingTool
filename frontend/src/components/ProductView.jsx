import React, { useEffect, useState } from 'react';
import { deleteClaim, dispositionClaim, editClaim, exportProduct, getProduct, productAction } from '../api.js';
import MarkingPicker from './MarkingPicker.jsx';

const STATE_LABELS = { draft: 'Draft', in_review: 'In review', approved: 'Approved, awaiting release', released: 'Released' };
const MODE_LABELS = { block: 'uncited claims block submission', acknowledge: 'uncited claims need a reviewer disposition', advisory: 'flags are advisory' };
const RULE_LABELS = { single: 'single reviewer releases', two_person: 'two-person review and release' };

function bannerStyle(banner) {
  if (!banner) return {};
  const lvl = banner.startsWith('TOP SECRET//SCI') ? 'TS/SCI' : banner.startsWith('TOP SECRET') ? 'TS'
    : banner.startsWith('SECRET') ? 'S' : banner.startsWith('CONFIDENTIAL') ? 'C' : 'U';
  const bg = { U: '#007a33', C: '#0033a0', S: '#c8102e', TS: '#ff8c00', 'TS/SCI': '#fce83a' }[lvl];
  return { background: bg, color: lvl === 'TS/SCI' ? '#1c1e21' : '#fff' };
}

export default function ProductView({ id, user }) {
  const [p, setP] = useState(null);
  const [error, setError] = useState(null);
  const [activeSource, setActiveSource] = useState(null);
  const [note, setNote] = useState('');
  const [dispo, setDispo] = useState({});

  const load = () => getProduct(id).then(setP).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [id]);

  const act = (fn) => async (...a) => {
    setError(null);
    try { const r = await fn(...a); if (r && r.id) setP(r); else await load(); } catch (e) { setError(e.message); }
  };

  async function download() {
    try {
      const md = await exportProduct(id);
      const url = URL.createObjectURL(new Blob([md], { type: 'text/markdown' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `${p.title.replace(/[^\w-]+/g, '_')}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) { setError(e.message); }
  }

  if (!p) return <div className="panel">{error ? <p className="error">{error}</p> : 'Loading'}</div>;

  const isAuthor = p.is_author;
  const roles = user.roles;
  const editable = isAuthor && p.state === 'draft';
  const reviewing = !isAuthor && p.state === 'in_review' && roles.includes('reviewer');
  const releasing = !isAuthor && p.state === 'approved' && roles.includes('releaser');
  const unmarked = p.claims.filter((c) => !c.portion_marking).length;

  return (
    <div className="product">
      <div className="banner-bar" style={bannerStyle(p.banner)}>{p.banner || 'UNMARKED'}</div>
      <div className="panel">
        <div className="header-row">
          <h2>{p.title}</h2>
          <span className={`state state-${p.state}`}>{STATE_LABELS[p.state]}</span>
        </div>
        <p className="muted">Author: {p.author}. Policy {p.policy_version ? `v${p.policy_version} (bound at submission)` : '(current)'}: {MODE_LABELS[p.citation_mode]}; {RULE_LABELS[p.review_rule]}.</p>
        {p.return_note && <p className="warn">Returned by reviewer: {p.return_note}</p>}
        <p className="question"><strong>Question.</strong> {p.question}</p>

        <div className="product-grid">
          <div>
            <h3>Claims</h3>
            {p.claims.map((c) => (
              <div key={c.id} className={`claim claim-${c.kind}${c.needs_disposition ? ' needs' : ''}`}>
                <div className="claim-head">
                  <span className="portion">{c.portion_marking || '(UNMARKED)'}</span>
                  <span className="claim-text">{c.text}</span>
                </div>
                <div className="claim-meta">
                  {c.cited_sources.map((n) => (
                    <button key={n} className={`cite${activeSource === n ? ' active' : ''}`} onClick={() => setActiveSource(n)}>S{n}</button>
                  ))}
                  {c.kind === 'uncited' && <span className="flag">No citation</span>}
                  {c.kind === 'judgment' && <span className="flag judgment">Analytic judgment</span>}
                  {c.invalid_refs.length > 0 && <span className="flag bad">Model cited nonexistent {c.invalid_refs.join(', ')}</span>}
                  {c.disposition && <span className="flag ok-flag">{p.dispositions[c.disposition]}{c.disposition_note ? `: ${c.disposition_note}` : ''}</span>}
                </div>
                {editable && (
                  <div className="claim-tools">
                    <MarkingPicker onApply={(m) => act(editClaim)(p.id, c.id, { portion_marking: m })} />
                    {c.derived_marking && <span className="muted small-text">Floor from sources: {c.derived_marking}</span>}
                    {c.kind !== 'cited' && (
                      <button className="link" onClick={() => act(editClaim)(p.id, c.id, { kind: c.kind === 'judgment' ? 'uncited' : 'judgment' })}>
                        {c.kind === 'judgment' ? 'Remove judgment tag' : 'Tag as my analytic judgment'}
                      </button>
                    )}
                    <button className="link danger" onClick={() => act(deleteClaim)(p.id, c.id)}>Delete claim</button>
                  </div>
                )}
                {reviewing && c.needs_disposition && (
                  <div className="claim-tools">
                    <select aria-label="Disposition" value={dispo[c.id]?.v || c.disposition || ''} onChange={(e) => setDispo({ ...dispo, [c.id]: { ...dispo[c.id], v: e.target.value } })}>
                      <option value="">Choose a disposition</option>
                      {Object.entries(p.dispositions).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                    </select>
                    <input placeholder="Note (optional)" value={dispo[c.id]?.n || ''} onChange={(e) => setDispo({ ...dispo, [c.id]: { ...dispo[c.id], n: e.target.value } })} />
                    <button className="small" disabled={!dispo[c.id]?.v} onClick={() => act(dispositionClaim)(p.id, c.id, dispo[c.id].v, dispo[c.id].n)}>Record</button>
                  </div>
                )}
              </div>
            ))}
          </div>
          <aside>
            <h3>Sources</h3>
            {p.sources.map((s) => (
              <div key={s.num} className={`source${activeSource === s.num ? ' active' : ''}`} onClick={() => setActiveSource(s.num)}>
                <div><strong>S{s.num}</strong> <span className="portion">{s.portion_marking}</span> {s.doc_title}</div>
                {activeSource === s.num && <p className="source-text">{s.content || 'Content not available to you.'}</p>}
              </div>
            ))}
            <h3>AI-assistance disclosure</h3>
            <dl className="disclosure">
              <dt>Model</dt><dd>{p.disclosure.model_name} ({p.disclosure.adapter})</dd>
              <dt>Requested / reported</dt><dd>{p.disclosure.model_requested} / {p.disclosure.model_reported || 'not reported'}</dd>
              <dt>Ceiling applied</dt><dd>{p.disclosure.ceiling}; {p.disclosure.withheld_count} retrieved item(s) withheld</dd>
              <dt>Prompt hash</dt><dd className="hash">{p.disclosure.prompt_sha256}</dd>
            </dl>
          </aside>
        </div>

        {error && <p className="error">{error}</p>}
        <div className="row actions-row">
          {editable && <button disabled={unmarked > 0} onClick={() => act(productAction)(p.id, 'submit')}>Submit for review</button>}
          {editable && unmarked > 0 && <span className="muted">{unmarked} claim(s) still need a portion marking.</span>}
          {reviewing && <button onClick={() => act(productAction)(p.id, 'approve')}>{p.review_rule === 'single' ? 'Approve and release' : 'Approve'}</button>}
          {releasing && <button onClick={() => act(productAction)(p.id, 'release')}>Release</button>}
          {(reviewing || releasing) && (
            <>
              <input className="grow" placeholder="Reason for returning to the author" value={note} onChange={(e) => setNote(e.target.value)} />
              <button className="secondary" disabled={!note.trim()} onClick={() => act(productAction)(p.id, 'return', { note })}>Return to author</button>
            </>
          )}
          <button className="secondary" onClick={download}>Export marked copy</button>
        </div>
      </div>
    </div>
  );
}
