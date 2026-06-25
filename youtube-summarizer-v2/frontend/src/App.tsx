import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api";
import Login from "./components/Login";
import StatusBar from "./components/StatusBar";
import SummariesPage from "./pages/SummariesPage";
import VideoPage from "./pages/VideoPage";
import SearchPage from "./pages/SearchPage";
import ChannelsPage from "./pages/ChannelsPage";

export default function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    api.me().then((r) => setAuthed(r.authenticated)).catch(() => setAuthed(false));
  }, []);

  if (authed === null) return <div className="app"><p className="muted">Loading…</p></div>;
  if (!authed) return <Login onLogin={() => setAuthed(true)} />;

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">▶ Summarizer</span>
        <nav>
          <NavLink to="/" end>Summaries</NavLink>
          <NavLink to="/search">Search</NavLink>
          <NavLink to="/channels">Channels</NavLink>
        </nav>
        <span className="spacer" />
        <button onClick={() => api.logout().then(() => setAuthed(false))}>Log out</button>
      </header>

      <StatusBar />

      <Routes>
        <Route path="/" element={<SummariesPage />} />
        <Route path="/videos/:id" element={<VideoPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/channels" element={<ChannelsPage />} />
      </Routes>
    </div>
  );
}
