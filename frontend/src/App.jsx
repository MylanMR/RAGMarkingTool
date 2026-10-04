import React, { useState } from 'react';
import IntakeForm from './components/IntakeForm.jsx';
import QueryInterface from './components/QueryInterface.jsx';

export default function App() {
  const [tab, setTab] = useState('intake');

  return (
    <div className="app">
      <div className="scaffold-banner">
        SCAFFOLDING — not accredited for classified information. Access control
        logic requires independent security review before use with real data.
      </div>
      <header className="app-header">
        <h1>Classification-Aware RAG Marking Tool</h1>
        <nav className="tabs">
          <button
            className={tab === 'intake' ? 'tab active' : 'tab'}
            onClick={() => setTab('intake')}
          >
            Document Intake
          </button>
          <button
            className={tab === 'query' ? 'tab active' : 'tab'}
            onClick={() => setTab('query')}
          >
            Query
          </button>
        </nav>
      </header>
      <main>{tab === 'intake' ? <IntakeForm /> : <QueryInterface />}</main>
    </div>
  );
}
