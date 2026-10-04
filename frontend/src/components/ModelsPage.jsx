import React, { useEffect, useState } from 'react';
import { addModel, approveModel, editModel, listAdapters, listModels, revokeModel } from '../api.js';
import { LEVELS, levelStyle } from '../marking.js';

const EMPTY = { name: '', adapter: '', base_url: '', model_id: '', max_classification: '', credential_ref: '', extra: '{}' };

const URL_HINTS = {
  openai_compatible: 'http://127.0.0.1:11434/v1 (Ollama) or https://api.openai.com/v1',
  azure_openai: 'https://<resource>.openai.azure.us',
  google_gemini: 'https://generativelanguage.googleapis.com/v1beta/models',
  anthropic: 'https://api.anthropic.com',
  aws_bedrock: 'https://bedrock-runtime.<region>.amazonaws.com',
  dev_extractive: 'local://dev',
};

export default function ModelsPage({ user }) {
  const isAdmin = user.roles.includes('admin');
  const isAO = user.roles.includes('ao');
  const [models, setModels] = useState([]);
  const [adapters, setAdapters] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState(null);

  const load = async () => { setModels(await listModels()); setAdapters(await listAdapters()); };
  useEffect(() => { load().catch((e) => setError(e.message)); }, []);

  const act = (fn) => async (...a) => { setError(null); try { await fn(...a); await load(); } catch (e) { setError(e.message); } };

  const create = act(async () => {
    let extra = {};
    try { extra = JSON.parse(form.extra || '{}'); } catch { throw new Error('Adapter options must be valid JSON.'); }
    await addModel({ ...form, credential_ref: form.credential_ref.trim() || null, extra });
    setForm(EMPTY);
  });

  const ready = form.name && form.adapter && form.base_url && form.model_id && form.max_classification;

  return (
    <div className="panel">
      <h2>Model endpoints</h2>
      <p className="hint">New endpoints start disabled. Under the AO-approved allowlist policy, any endpoint outside this host or the declared enclave networks also needs AO approval. Changing an endpoint's address, model, adapter, or ceiling clears its approval.</p>
      {error && <p className="error">{error}</p>}
      <table className="simple">
        <thead><tr><th>Name</th><th>Adapter</th><th>Model</th><th>Ceiling</th><th>Location</th><th>AO approval</th><th>Status</th><th /></tr></thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.id}>
              <td>{m.name}</td>
              <td>{m.adapter}</td>
              <td>{m.model_id}</td>
              <td><span className="marking-chip" style={levelStyle(m.max_classification)}>{m.max_classification}</span></td>
              <td>{m.local ? 'Local / enclave' : 'External'}</td>
              <td>{m.approved_by ? `${m.approved_by}` : (m.local ? 'Not required' : 'Pending')}</td>
              <td>{m.enabled ? 'Enabled' : 'Disabled'}</td>
              <td className="actions">
                {isAdmin && <button className="link" onClick={() => act(editModel)(m.id, { enabled: !m.enabled })}>{m.enabled ? 'Disable' : 'Enable'}</button>}
                {isAO && !m.approved_by && !m.local && <button className="link" onClick={() => act(approveModel)(m.id)}>Approve</button>}
                {isAO && m.approved_by && <button className="link danger" onClick={() => act(revokeModel)(m.id)}>Revoke</button>}
              </td>
            </tr>
          ))}
          {models.length === 0 && <tr><td colSpan={8} className="muted">No endpoints yet. An administrator adds the first one below.</td></tr>}
        </tbody>
      </table>

      {isAdmin && (
        <fieldset className="section-marker">
          <legend>Add endpoint</legend>
          <div className="row">
            <label>Name<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Enclave Llama 3" /></label>
            <label>Adapter
              <select value={form.adapter} onChange={(e) => setForm({ ...form, adapter: e.target.value })}>
                <option value="">Choose an adapter</option>
                {adapters.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
              </select>
            </label>
          </div>
          <div className="row">
            <label>Base URL<input value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder={URL_HINTS[form.adapter] || 'https://'} /></label>
            <label>Model or deployment ID<input value={form.model_id} onChange={(e) => setForm({ ...form, model_id: e.target.value })} /></label>
          </div>
          <div className="row">
            <label>Approved classification ceiling
              <select value={form.max_classification} onChange={(e) => setForm({ ...form, max_classification: e.target.value })}>
                <option value="">Choose a ceiling</option>
                {LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
              </select>
            </label>
            <label>Credential reference
              <input value={form.credential_ref} onChange={(e) => setForm({ ...form, credential_ref: e.target.value })} placeholder="env:OPENAI_API_KEY or file:/etc/ragmt/keys/openai" />
            </label>
          </div>
          <label>Adapter options (JSON)
            <input value={form.extra} onChange={(e) => setForm({ ...form, extra: e.target.value })} placeholder='{"api_version": "2024-06-01"} or {"region": "us-gov-west-1"}' />
          </label>
          <p className="hint">Enter a reference to where the secret lives, never the secret itself. The service account reads it at call time.</p>
          <button disabled={!ready} onClick={create}>Add endpoint</button>
        </fieldset>
      )}
    </div>
  );
}
