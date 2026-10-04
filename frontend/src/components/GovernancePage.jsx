import React, { useEffect, useState } from 'react';
import { govEvents, govVerify } from '../api.js';

export default function GovernancePage() {
  const [events, setEvents] = useState([]);
  const [filter, setFilter] = useState('');
  const [verify, setVerify] = useState(null);
  const [open, setOpen] = useState(null);
  const [error, setError] = useState(null);

  const load = () => govEvents(filter ? `?event_type=${encodeURIComponent(filter)}` : '').then(setEvents).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [filter]);

  return (
    <div className="panel">
      <h2>Governance log</h2>
      <p className="hint">Every policy change, model approval, account change, and product transition, chained by SHA-256 so any edited or deleted entry is detectable.</p>
      <div className="row">
        <label>Event type
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">All events</option>
            <option value="policy.*">Policy changes</option>
            <option value="model.*">Model endpoints</option>
            <option value="product.*">Product workflow</option>
            <option value="user.*">Account administration</option>
            <option value="auth.*">Sign-in activity</option>
          </select>
        </label>
        <button onClick={() => govVerify().then(setVerify).catch((e) => setError(e.message))}>Verify chain integrity</button>
      </div>
      {verify && (
        <p className={verify.intact ? 'ok' : 'error'}>
          {verify.intact ? `Chain intact: ${verify.events_checked} events verified.`
            : `Chain broken at event ${verify.first_bad_seq}. Preserve the database and notify the ISSM.`}
        </p>
      )}
      {error && <p className="error">{error}</p>}
      <table className="simple clickable">
        <thead><tr><th>#</th><th>When</th><th>Actor</th><th>Event</th><th>Subject</th></tr></thead>
        <tbody>{events.map((e) => (
          <React.Fragment key={e.seq}>
            <tr onClick={() => setOpen(open === e.seq ? null : e.seq)}>
              <td>{e.seq}</td><td>{new Date(e.ts).toLocaleString()}</td><td>{e.actor}</td><td>{e.event_type}</td><td className="hash">{e.subject_type} {e.subject_id.slice(0, 8)}</td>
            </tr>
            {open === e.seq && <tr><td colSpan={5}><pre className="payload">{JSON.stringify(e.payload, null, 2)}</pre><div className="hash">hash {e.hash}</div></td></tr>}
          </React.Fragment>))}</tbody>
      </table>
    </div>
  );
}
