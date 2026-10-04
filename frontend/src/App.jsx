import React, { useEffect, useState } from 'react';
import { logout, onSessionExpired, setToken } from './api.js';
import { levelStyle } from './marking.js';
import Login, { ChangePassword } from './components/Login.jsx';
import IntakeForm from './components/IntakeForm.jsx';
import QueryInterface from './components/QueryInterface.jsx';
import DraftWorkspace from './components/DraftWorkspace.jsx';
import ProductList from './components/ProductList.jsx';
import PolicyPage from './components/PolicyPage.jsx';
import ModelsPage from './components/ModelsPage.jsx';
import UsersPage from './components/UsersPage.jsx';
import GovernancePage from './components/GovernancePage.jsx';

// Tabs appear only for the roles that can use them. The server enforces
// every rule regardless; hiding tabs is convenience, not access control.
const TABS = [
  { id: 'draft', label: 'Draft', roles: ['author'] },
  { id: 'mine', label: 'My products', roles: ['author'] },
  { id: 'review', label: 'Review', roles: ['reviewer'] },
  { id: 'release', label: 'Release', roles: ['releaser'] },
  { id: 'released', label: 'Released', roles: null },
  { id: 'intake', label: 'Intake', roles: ['author', 'admin'] },
  { id: 'query', label: 'Search', roles: null },
  { id: 'policy', label: 'Risk policy', roles: null },
  { id: 'models', label: 'Models', roles: ['admin', 'ao', 'auditor'] },
  { id: 'users', label: 'Users', roles: ['admin', 'auditor'] },
  { id: 'governance', label: 'Governance log', roles: ['auditor', 'ao'] },
];

export default function App() {
  const [session, setSession] = useState(null);
  const [tab, setTab] = useState(null);
  const [notice, setNotice] = useState(null);

  useEffect(() => onSessionExpired(() => {
    setSession(null);
    setNotice('Your session ended. Sign in again.');
  }), []);

  function signedIn(s) {
    setToken(s.token);
    setSession(s);
    setNotice(null);
    const first = TABS.find((t) => !t.roles || t.roles.some((r) => s.user.roles.includes(r)));
    setTab(first ? first.id : 'policy');
  }

  async function signOut() {
    try { await logout(); } catch { /* already gone */ }
    setToken(null);
    setSession(null);
  }

  if (!session) return <div className="app"><Shell /><Login onSignedIn={signedIn} notice={notice} /></div>;
  if (session.user.must_change_password) {
    return <div className="app"><Shell /><ChangePassword onChanged={signedIn} /></div>;
  }

  const u = session.user;
  const tabs = TABS.filter((t) => !t.roles || t.roles.some((r) => u.roles.includes(r)));
  const roles = u.roles;

  return (
    <div className="app">
      <Shell />
      <header className="app-header">
        <div className="header-row">
          <h1>RAG Marking Tool</h1>
          <div className="whoami">
            <span>{u.display_name}</span>
            <span className="marking-chip" style={levelStyle(u.clearance)}>{u.clearance}</span>
            <span className="muted">{roles.join(', ')}</span>
            <button className="secondary small" onClick={signOut}>Sign out</button>
          </div>
        </div>
        <nav className="tabs">
          {tabs.map((t) => (
            <button key={t.id} className={tab === t.id ? 'tab active' : 'tab'} onClick={() => setTab(t.id)}>
              {t.label}
            </button>
          ))}
        </nav>
      </header>
      <main>
        {tab === 'draft' && <DraftWorkspace user={u} />}
        {['mine', 'review', 'release', 'released'].includes(tab) && <ProductList key={tab} view={tab} user={u} />}
        {tab === 'intake' && <IntakeForm />}
        {tab === 'query' && <QueryInterface />}
        {tab === 'policy' && <PolicyPage user={u} />}
        {tab === 'models' && <ModelsPage user={u} />}
        {tab === 'users' && <UsersPage user={u} />}
        {tab === 'governance' && <GovernancePage />}
      </main>
    </div>
  );
}

function Shell() {
  return (
    <div className="scaffold-banner">
      Not accredited until independently reviewed. Do not process real classified information
      without an authorization decision.
    </div>
  );
}
