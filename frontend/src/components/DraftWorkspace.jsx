import React, { useEffect, useState } from 'react';
import { draftProduct, listModels } from '../api.js';
import { levelStyle } from '../marking.js';
import ProductView from './ProductView.jsx';

export default function DraftWorkspace({ user }) {
  const [models, setModels] = useState([]);
  const [title, setTitle] = useState('');
  const [question, setQuestion] = useState('');
  const [modelId, setModelId] = useState('');
  const [topK, setTopK] = useState(8);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [productId, setProductId] = useState(null);

  useEffect(() => { listModels().then((m) => setModels(m.filter((x) => x.enabled))).catch((e) => setError(e.message)); }, []);

  async function run(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const p = await draftProduct({ title: title.trim(), question: question.trim(), model_endpoint_id: modelId, top_k: Number(topK) });
      setProductId(p.id);
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }

  if (productId) {
    return (
      <>
        <button className="link" onClick={() => setProductId(null)}>Start another draft</button>
        <ProductView id={productId} user={user} />
      </>
    );
  }

  const chosen = models.find((m) => m.id === modelId);
  return (
    <form className="panel" onSubmit={run}>
      <h2>Draft with AI assistance</h2>
      <p className="hint">The tool searches only material you're cleared for, withholds anything above the selected model's ceiling, and asks the model to cite every sentence. You'll mark and check every claim before it can go to review.</p>
      <label>Title<input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Vessel Alpha cargo assessment" /></label>
      <label>Question<textarea rows={4} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="What do holdings say about the cargo aboard Vessel Alpha?" /></label>
      <div className="row">
        <label>Model
          <select value={modelId} onChange={(e) => setModelId(e.target.value)}>
            <option value="">Choose a model</option>
            {models.map((m) => <option key={m.id} value={m.id}>{m.name} (ceiling {m.max_classification})</option>)}
          </select>
        </label>
        <label className="narrow-field">Sources to retrieve
          <select value={topK} onChange={(e) => setTopK(e.target.value)}>
            {[4, 8, 12, 20].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
      </div>
      {chosen && (
        <p className="hint">Content above <span className="marking-chip" style={levelStyle(chosen.max_classification)}>{chosen.max_classification}</span> will be withheld from this model{user.clearance !== chosen.max_classification ? ', even though you may be cleared for it' : ''}.</p>
      )}
      {models.length === 0 && <p className="warn">No models are enabled. Ask an administrator to add one.</p>}
      {error && <p className="error">{error}</p>}
      <button disabled={busy || !title.trim() || !question.trim() || !modelId}>{busy ? 'Drafting' : 'Draft'}</button>
    </form>
  );
}
