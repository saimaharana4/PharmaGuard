"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ApiError, investigate, renewSession } from "@/lib/api";
import { sourceUrl, type Investigation, type Question } from "@/lib/schemas";

type Entry = {id: string; question: Question} & (
  {state: "loading"} | {state: "success"; result: Investigation} |
  {state: "error"; message: string; requestId?: string}
);
const prompts = [
  "What does recent evidence say about semaglutide and pancreatitis?",
  "What does semaglutide label evidence say about pancreatitis?",
  "What uncertainty remains in the semaglutide and pancreatitis literature?",
];
const dateLabel = (value: string) => new Date(`${value}T00:00:00Z`).toLocaleDateString("en-GB", {day: "numeric", month: "short", year: "numeric", timeZone: "UTC"});
const metric = (value: number | null) => value === null ? "Unavailable" : value.toLocaleString("en", {maximumFractionDigits: 3});

export default function Workspace() {
  const [question, setQuestion] = useState("");
  const [drug, setDrug] = useState("");
  const [event, setEvent] = useState("");
  const [cutoff, setCutoff] = useState("");
  const [filters, setFilters] = useState(false);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [memory, setMemory] = useState<{question: string; answer: string}[]>([]);
  const [selected, setSelected] = useState<Investigation | null>(null);
  const [online, setOnline] = useState<"checking" | "ready" | "unavailable">("checking");
  const [build, setBuild] = useState("");
  const [highlight, setHighlight] = useState("");
  const threadEnd = useRef<HTMLDivElement>(null);
  const busy = entries.some(entry => entry.state === "loading");

  useEffect(() => {
    void renewSession().then(setMemory).catch(() => undefined);
    // Refresh only while the page is open. Idle/closed sessions expire after one hour.
    const timer = setInterval(() => { void renewSession().catch(() => undefined); }, 55 * 60 * 1000);
    fetch("/api/ready").then(r => setOnline(r.ok ? "ready" : "unavailable")).catch(() => setOnline("unavailable"));
    fetch("/api/version").then(r => r.ok ? r.json() : null).then(v => setBuild(v?.git_sha?.slice(0, 8) ?? "")).catch(() => setBuild(""));
    return () => clearInterval(timer);
  }, []);

  async function submit(input?: Question) {
    const payload = input ?? {question: question.trim(), ...(drug && {drug}), ...(event && {event}), ...(cutoff && {cutoff_date: cutoff})};
    if (busy || payload.question.trim().length < 3) return;
    const id = crypto.randomUUID();
    setEntries(current => [...current, {id, question: payload, state: "loading"}]);
    setQuestion("");
    try {
      const result = await investigate(payload);
      setEntries(current => current.map(entry => entry.id === id ? {id, question: payload, state: "success", result} : entry));
      setSelected(result);
      setOnline("ready");
    } catch (error) {
      setEntries(current => current.map(entry => entry.id === id ? {id, question: payload, state: "error", message: error instanceof Error ? error.message : "Request failed.", requestId: error instanceof ApiError ? error.requestId : undefined} : entry));
    }
    threadEnd.current?.scrollIntoView({behavior: "smooth", block: "nearest"});
  }

  function citation(id: string, result: Investigation) {
    setSelected(result); setHighlight(id);
    setTimeout(() => {document.getElementById(`evidence-${id}`)?.scrollIntoView({behavior: "smooth", block: "center"}); document.getElementById(`evidence-${id}`)?.focus();}, 0);
  }

  function answer(result: Investigation) {
    const parts = result.answer.split(/(\[[0-9a-f-]{36}\])/g);
    return parts.map((part, index) => {
      const hit = result.citations.find(c => `[${c.chunk_id}]` === part);
      return hit ? <button className="citation" key={index} onClick={() => citation(hit.chunk_id, result)} aria-label={`Inspect source ${result.citations.indexOf(hit) + 1}`}>[{result.citations.indexOf(hit) + 1}]</button> : <Fragment key={index}>{part}</Fragment>;
    });
  }

  return <div className="workspace">
    <a href="#composer" className="skip-link">Skip to question</a>
    <header className="header">
      <Link href="/" className="brand" aria-label="PharmaGuard AI home"><span className="brand-mark" aria-hidden="true">P<span>+</span></span><span>PharmaGuard <b>AI</b><small>EVIDENCE INTELLIGENCE</small></span></Link>
      <div className="header-status"><span className="window-badge">24-month source window</span><span className={`status ${online}`}><i aria-hidden="true" />{online === "ready" ? "System ready" : online === "checking" ? "Checking system" : "Setup required"}</span></div>
    </header>
    <main className="main-grid">
      <section className="chat-workspace" aria-label="Investigation workspace">
        {!!memory.length && <details className="provenance"><summary>Previous session exchanges ({memory.length}/5)</summary><p>Conversation context only. Submit the question again to validate current facts and sources.</p>{memory.map((item, index) => <div key={index}><b>{item.question}</b><p>{item.answer.replace(/\[[0-9a-f-]{36}\]/g, "")}</p></div>)}</details>}
        <div className="workspace-label"><span>RESEARCH WORKSPACE</span><span>PUBLIC SOURCE DATA</span></div>
        {!entries.length ? <div className="empty-state">
          <span className="eyebrow"><span aria-hidden="true">✳</span> A clearer view of the evidence</span>
          <h1>Follow the signal.<br /><span>Inspect the evidence.</span></h1>
          <p>Investigate drug-safety questions with structured reporting signals, published research, and versioned label evidence.</p>
          <div className="principles"><span>01 <b>Deterministic facts</b></span><span>02 <b>Traceable sources</b></span><span>03 <b>Explicit uncertainty</b></span></div>
          <div className="prompt-label">START AN INVESTIGATION</div>
          <div className="prompts">{prompts.map((prompt, i) => <button key={prompt} onClick={() => setQuestion(prompt)}><span className="prompt-number">0{i + 1}</span><span>{prompt}</span><span aria-hidden="true">↗</span></button>)}</div>
          <p className="scope-note">Initial evidence scope: semaglutide / pancreatitis. Availability depends on the published dataset.</p>
        </div> : <div className="thread" aria-live="polite" aria-relevant="additions text">{entries.map(entry => <article key={entry.id} className="exchange">
          <div className="user-question"><span className="meta-label">YOUR QUESTION</span><p>{entry.question.question}</p></div>
          <div className="assistant-label"><span className="mini-mark" aria-hidden="true">P+</span><b>PharmaGuard AI</b></div>
          {entry.state === "loading" ? <div className="loading" role="status"><span className="spinner" />Investigating the published evidence…</div> : entry.state === "error" ? <div className="error" role="alert"><b>Investigation unavailable</b><p>{entry.message}</p>{entry.requestId && <small>Request ID: {entry.requestId}</small>}<button className="text-button" disabled={busy} onClick={() => submit(entry.question)}>Retry investigation ↗</button></div> : <>
            {entry.result.insufficient_evidence && <div className="abstention">Insufficient qualifying evidence</div>}
            <div className="answer-text">{answer(entry.result)}</div>
            {entry.result.session_id && <p className="scope-note">Session memory: newest five exchanges. {entry.result.cache_status === "hit" ? "Reused a validated answer; no model call." : "Answer checked against the published corpus."}</p>}
            <div className="signal-card"><div className="card-heading"><b>Signal summary</b><span>COMPUTED FROM REPORTS</span></div>
              <p className="period">Report pair: {entry.result.facts.drug ?? "unresolved drug"} / {entry.result.facts.event ?? "unresolved event"}</p><p className="period">Latest included FDA release: {entry.result.facts.source_releases.at(-1) ?? "unavailable"}</p><div className="metrics"><div><span>Case count</span><strong>{metric(entry.result.facts.case_count)}</strong></div><div><span title="Reporting odds ratio">ROR</span><strong>{metric(entry.result.facts.ror)}</strong></div><div><span title="Proportional reporting ratio">PRR</span><strong>{metric(entry.result.facts.prr)}</strong></div></div>
              <div className="period">{dateLabel(entry.result.facts.period_start)} — {dateLabel(entry.result.facts.period_end)}</div>
              {entry.result.facts.reason && <p className="metric-reason">{entry.result.facts.reason}</p>}
              <p className="metric-disclaimer">Spontaneous reports can identify signals; they do not establish causality.</p>
            </div>
            <button className="evidence-toggle" onClick={() => {setSelected(entry.result); document.getElementById("evidence-panel")?.scrollIntoView({behavior: "smooth", block: "nearest"});}}>Inspect {entry.result.citations.length} cited excerpts <span aria-hidden="true">↗</span></button>
            <details className="provenance"><summary>Data coverage and limitations</summary><p>Published dataset: {entry.result.data_window.dataset_id}</p><p>Window: {dateLabel(entry.result.data_window.window_start)} — {dateLabel(entry.result.data_window.as_of_date)}</p>{entry.result.warnings.map(w => <p key={w}>{w}</p>)}<p>Evidence cutoff: {dateLabel(entry.result.data_window.cutoff_date)}</p><p>Reports received: {dateLabel(entry.result.facts.period_start)} to {dateLabel(entry.result.facts.period_end)}</p><p>Request ID: {entry.result.request_id}</p></details>
          </>}
        </article>)}<div ref={threadEnd} /></div>}
        <form id="composer" className="composer" onSubmit={e => {e.preventDefault(); void submit();}}>
          {filters && <div className="filters"><label>Drug<input value={drug} onChange={e => setDrug(e.target.value)} placeholder="e.g. semaglutide" maxLength={200} /></label><label>Event<input value={event} onChange={e => setEvent(e.target.value)} placeholder="e.g. pancreatitis" maxLength={200} /></label><label>Evidence cutoff<input type="date" value={cutoff} onChange={e => setCutoff(e.target.value)} /></label></div>}
          <label htmlFor="question" className="sr-only">Ask a drug-safety question</label>
          <textarea id="question" value={question} maxLength={2000} onChange={e => setQuestion(e.target.value)} onKeyDown={e => {if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {e.preventDefault(); void submit();}}} placeholder="Ask a drug-safety question…" rows={2} disabled={busy} />
          <div className="composer-actions"><button type="button" className={`filter-button ${filters ? "active" : ""}`} onClick={() => setFilters(!filters)} aria-expanded={filters}>☷ Filters</button><span className="keyboard-hint">Enter to send · Shift + Enter for a new line</span><button type="submit" className="send-button" disabled={busy || question.trim().length < 3}>Investigate <span aria-hidden="true">↑</span></button></div>
        </form>
      </section>
      <aside id="evidence-panel" className="evidence-panel" aria-label="Evidence sources">
        <div className="panel-heading"><div><span className="meta-label">SOURCE LIBRARY</span><h2>Evidence</h2></div><span className="source-count">{selected?.citations.length ?? 0}</span></div>
        {selected ? <><p className="panel-description">Inspect the cited excerpts. Multiple excerpts may come from one document; a citation alone does not prove a claim.</p>{selected.citations.length === 0 && <p className="no-sources">No sources cited for this response.</p>}{selected.citations.map((hit, index) => <article id={`evidence-${hit.chunk_id}`} key={hit.chunk_id} tabIndex={-1} className={`evidence-card ${highlight === hit.chunk_id ? "highlight" : ""}`}>
          <div className="source-row"><span className={`source-badge ${hit.source_type}`}>{hit.source_type === "pubmed" ? "PubMed" : "DailyMed"}</span><span className="evidence-number">[{index + 1}]</span></div><h3>{hit.title}</h3><p className="source-meta">Published {dateLabel(hit.source_date)} · Version available {dateLabel(hit.available_at)}</p><p className="locator">{hit.locator}</p><blockquote>{hit.text}</blockquote>{sourceUrl(hit.url) && <a href={sourceUrl(hit.url)!} target="_blank" rel="noopener noreferrer">Open versioned source ↗</a>}
        </article>)}</> : <div className="evidence-empty"><div className="document-icon" aria-hidden="true"><span /><span /><span /></div><h3>Every answer has a source trail.</h3><p>Cited research and label excerpts appear here after an investigation.</p><div className="source-types"><span>PubMed</span><span>DailyMed</span><span>FDA reports</span></div></div>}
        <div className="evidence-footnote"><span aria-hidden="true">↳</span> Source dates and historical cutoffs are checked before evidence is returned.</div>
      </aside>
    </main>
    <footer className="footer"><p>For drug-safety signal investigation and evidence review only. <b>Not medical advice or proof of causality.</b></p><span>RESEARCH PROTOTYPE{build ? ` · ${build}` : ""}</span></footer>
  </div>;
}
