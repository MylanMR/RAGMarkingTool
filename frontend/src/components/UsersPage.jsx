import React, { useEffect, useState } from 'react';
import { addUser, editUser, listUsers, resetPassword, unlockUser } from '../api.js';
import { LEVELS, levelStyle, parseList } from '../marking.js';

const ROLES = [
  ['author', 'Author'], ['reviewer', 'Reviewer'], ['releaser', 'Releaser'],
  ['admin', 'System administrator'], ['ao', 'Authorizing Official'], ['auditor', 'Auditor'],
];
const BLANK = { username: '', display_name: '', auth_source: 'local', initial_password: '', roles: [], clearance: '', citizenship: '', compartments: '', ntk: '' };

export default function UsersPage({ user }) {
  const isAdmin = user.roles.includes('admin');
  const [users, setUsers] = useState([]);
  const [f, setF] = useState(BLANK);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);

  const load = () => listUsers().then(setUsers).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);
  const act = (fn, done) => async (...a) => { setError(null); setMsg(null); try { await fn(...a); if (done) setMsg(done); await load(); } catch (e) { setError(e.message); } };

  const toggleRole = (r) => setF({ ...f, roles: f.roles.includes(r) ? f.roles.filter((x) => x !== r) : [...f.roles, r] });
  const create = act(async () => {
    await addUser({ username: f.username.trim(), display_name: f.display_name.trim(), auth_source: f.auth_source,
      initial_password: f.auth_source === 'local' ? f.initial_password : null, roles: f.roles, clearance: f.clearance,
      citizenship: f.citizenship.trim().toUpperCase(), compartments: parseList(f.compartments), need_to_know_groups: parseList(f.ntk) });
    setF(BLANK);
  }, 'Account created. The user must change the temporary password at first sign-in.');

  return (
    <div className="panel">
      <h2>Users</h2>
      <p className="hint">Clearance, citizenship, compartments, and need-to-know groups set here are what the access control decision uses. Changing them signs the user out everywhere.</p>
      {error && <p className="error">{error}</p>}
      {msg && <p className="ok">{msg}</p>}
      <table className="simple">
        <thead><tr><th>User</th><th>Source</th><th>Roles</th><th>Clearance</th><th>Citizenship</th><th>Status</th><th /></tr></thead>
        <tbody>{users.map((u) => (
          <tr key={u.id}>
            <td>{u.display_name}<div className="muted small-text">{u.username}</div></td>
            <td>{u.auth_source}</td><td>{u.roles.join(', ')}</td>
            <td><span className="marking-chip" style={levelStyle(u.clearance)}>{u.clearance}</span></td>
            <td>{u.citizenship}</td>
            <td>{!u.active ? 'Disabled' : u.locked ? 'Locked' : 'Active'}</td>
            <td className="actions">{isAdmin && u.id !== user.id && (<>
              {u.locked && <button className="link" onClick={() => act(unlockUser, 'Unlocked.')(u.id)}>Unlock</button>}
              <button className="link" onClick={() => act(editUser, u.active ? 'Disabled.' : 'Enabled.')(u.id, { active: !u.active })}>{u.active ? 'Disable' : 'Enable'}</button>
              {u.auth_source === 'local' && <button className="link" onClick={() => {
                const pw = window.prompt(`Temporary password for ${u.username} (15+ characters):`);
                if (pw) act(resetPassword, 'Password reset. The user must change it at next sign-in.')(u.id, pw);
              }}>Reset password</button>}
            </>)}</td>
          </tr>))}</tbody>
      </table>

      {isAdmin && (
        <fieldset className="section-marker">
          <legend>Add user</legend>
          <div className="row">
            <label>Username<input value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} /></label>
            <label>Display name<input value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} /></label>
            <label>Sign-in source
              <select value={f.auth_source} onChange={(e) => setF({ ...f, auth_source: e.target.value })}>
                <option value="local">Local account</option>
                <option value="ad">Active Directory (Windows sign-in)</option>
                <option value="oidc">OIDC single sign-on (when enabled)</option>
                <option value="saml">SAML single sign-on (when enabled)</option>
              </select>
            </label>
          </div>
          {f.auth_source === 'local' && (
            <label>Temporary password<input type="password" autoComplete="new-password" value={f.initial_password} onChange={(e) => setF({ ...f, initial_password: e.target.value })} /></label>
          )}
          <div className="role-boxes">
            {ROLES.map(([r, label]) => (
              <label key={r} className="checkbox"><input type="checkbox" checked={f.roles.includes(r)} onChange={() => toggleRole(r)} /> {label}</label>
            ))}
          </div>
          <div className="row">
            <label>Clearance
              <select value={f.clearance} onChange={(e) => setF({ ...f, clearance: e.target.value })}>
                <option value="">Choose clearance</option>
                {LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
              </select>
            </label>
            <label>Citizenship (trigraph)<input maxLength={3} value={f.citizenship} onChange={(e) => setF({ ...f, citizenship: e.target.value })} placeholder="USA" /></label>
          </div>
          <div className="row">
            <label>Compartments (comma-separated)<input value={f.compartments} onChange={(e) => setF({ ...f, compartments: e.target.value })} /></label>
            <label>Need-to-know groups (comma-separated)<input value={f.ntk} onChange={(e) => setF({ ...f, ntk: e.target.value })} placeholder="ORCON, PROPIN" /></label>
          </div>
          <button disabled={!f.username || !f.display_name || !f.roles.length || !f.clearance || f.citizenship.length !== 3} onClick={create}>Add user</button>
        </fieldset>
      )}
    </div>
  );
}
