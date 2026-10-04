import React, { useEffect, useState } from 'react';
import { authProviders, changePassword, login, setToken, windowsSignIn } from '../api.js';

export default function Login({ onSignedIn, notice }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [ad, setAd] = useState(false);

  useEffect(() => { authProviders().then((p) => setAd(!!p.ad)).catch(() => setAd(false)); }, []);

  async function windows() {
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await windowsSignIn());
    } catch (err) {
      setError(err.message === 'Windows sign-in required'
        ? 'Your browser did not offer Windows credentials. Use a domain-joined computer, or ask your administrator to add this site to the browser\'s integrated authentication list.'
        : err.message);
    } finally {
      setBusy(false);
    }
  }

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await login(username.trim(), password));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
      setPassword('');
    }
  }

  return (
    <form className="panel narrow" onSubmit={submit}>
      <h2>Sign in</h2>
      {notice && <p className="hint">{notice}</p>}
      {ad && (
        <>
          <button type="button" disabled={busy} onClick={windows}>Sign in with Windows</button>
          <p className="divider-text">or use a local account</p>
        </>
      )}
      <label>Username<input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} /></label>
      <label>Password<input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
      {error && <p className="error">{error}</p>}
      <button disabled={busy || !username || !password}>{busy ? 'Signing in' : 'Sign in'}</button>
    </form>
  );
}

export function ChangePassword({ onChanged }) {
  const [cur, setCur] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState(null);

  async function submit(e) {
    e.preventDefault();
    setError(null);
    if (next !== confirm) { setError('New passwords do not match.'); return; }
    try {
      const s = await changePassword(cur, next);
      setToken(s.token);
      onChanged(s);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <form className="panel narrow" onSubmit={submit}>
      <h2>Set a new password</h2>
      <p className="hint">Your administrator issued a temporary password. Choose a new one: at least 15 characters, using 3 of lowercase, uppercase, digits, and symbols.</p>
      <label>Temporary password<input type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} /></label>
      <label>New password<input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} /></label>
      <label>Confirm new password<input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} /></label>
      {error && <p className="error">{error}</p>}
      <button disabled={!cur || !next || !confirm}>Save password</button>
    </form>
  );
}
