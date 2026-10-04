// Thin fetch wrapper: JSON in/out, FastAPI error detail extraction.

async function request(path, options = {}) {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  let body = null;
  try {
    body = await resp.json();
  } catch {
    // non-JSON error body; fall through
  }
  if (!resp.ok) {
    const detail =
      body && body.detail
        ? typeof body.detail === 'string'
          ? body.detail
          : JSON.stringify(body.detail)
        : `${resp.status} ${resp.statusText}`;
    throw new Error(detail);
  }
  return body;
}

export function ingestDocument(payload) {
  return request('/ingest/documents', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function embedDocument(docId) {
  return request(`/ingest/documents/${encodeURIComponent(docId)}/embed`, {
    method: 'POST',
  });
}

export function runQuery(payload) {
  return request('/query', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}
