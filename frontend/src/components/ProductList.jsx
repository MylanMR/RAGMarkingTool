import React, { useEffect, useState } from 'react';
import { listProducts } from '../api.js';
import ProductView from './ProductView.jsx';

const EMPTY = {
  mine: 'You have no products yet. Start one from the Draft tab.',
  review: 'Nothing is waiting for your review.',
  release: 'Nothing is waiting for release.',
  released: 'No released products you are cleared to see.',
};

export default function ProductList({ view, user }) {
  const [items, setItems] = useState(null);
  const [open, setOpen] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => { if (!open) listProducts(view).then(setItems).catch((e) => setError(e.message)); }, [view, open]);

  if (open) return (<><button className="link" onClick={() => setOpen(null)}>Back to list</button><ProductView id={open} user={user} /></>);

  return (
    <div className="panel">
      {error && <p className="error">{error}</p>}
      {items && items.length === 0 && <p className="muted">{EMPTY[view]}</p>}
      {items && items.length > 0 && (
        <table className="simple clickable">
          <thead><tr><th>Title</th><th>Banner</th><th>State</th><th>Author</th><th>Flags</th><th>Updated</th></tr></thead>
          <tbody>
            {items.map((p) => (
              <tr key={p.id} onClick={() => setOpen(p.id)} tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && setOpen(p.id)}>
                <td>{p.title}</td><td>{p.banner}</td><td>{p.state.replace('_', ' ')}</td><td>{p.author}</td>
                <td>{p.counts.uncited ? `${p.counts.uncited} uncited ` : ''}{p.counts.judgment ? `${p.counts.judgment} judgment ` : ''}{p.counts.invalid_refs ? `${p.counts.invalid_refs} bad refs` : ''}</td>
                <td>{new Date(p.updated_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
