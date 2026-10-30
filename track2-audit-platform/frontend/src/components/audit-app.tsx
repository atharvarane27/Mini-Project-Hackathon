"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { FormEvent, ReactNode, useCallback, useEffect, useState } from "react";
import {
  CircleDollarSign, FileSearch, FileUp, Fingerprint, GitBranch,
  LayoutDashboard, LogIn, Menu, Network, Search, ShieldCheck, SlidersHorizontal,
  X,
} from "lucide-react";
import {
  ApiError, AuditCase, DuplicateEvidence, Finding, IngestionJob, Metrics,
  Transaction, claimCase, createCase, createIngestionJob, getMetrics,
  listCases, listDuplicates, listFindings, listTransactions, login,
  runDetector, runReconciliation, session,
} from "@/lib/api";

export type View = "dashboard" | "ingestion" | "transactions" | "duplicates" |
  "findings" | "reconciliation" | "circular" | "splitting" | "cases" |
  "login";

const navigation = [
  ["/dashboard/", "Overview", LayoutDashboard], ["/ingestion/", "Data ingestion", FileUp],
  ["/transactions/", "Transactions", CircleDollarSign], ["/duplicates/", "Duplicates", Fingerprint],
  ["/reconciliation/", "Reconciliation", GitBranch], ["/patterns/circular/", "Circular flow", Network],
  ["/patterns/splitting/", "Splitting", SlidersHorizontal], ["/findings/", "Findings", Fingerprint],
  ["/cases/", "Cases", FileSearch],
] as const;

function message(error: unknown): string {
  if (error instanceof ApiError) return `${error.message} (${error.code})${error.requestId ? ` · ${error.requestId}` : ""}`;
  return error instanceof Error ? error.message : "Unexpected error";
}

function numericCode(value: string, digits = 4): string {
  let hash = 0;
  for (const character of value) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return String(hash % (10 ** digits)).padStart(digits, "0");
}

function transactionLabel(reference: string, occurredAt: string): string {
  if (/^TXN-\d{8}-\d{4,}$/.test(reference)) return reference;
  const date = occurredAt.slice(0, 10).replaceAll("-", "");
  return `TXN-${date}-${numericCode(reference, 6)}`;
}

function accountLabel(accountId: string): string {
  const digits = accountId.replace(/\D/g, "");
  const suffix = digits.length >= 4 ? digits.slice(-4) : numericCode(accountId);
  return `A/C •••• ${suffix}`;
}

function recordLabel(recordId: string): string {
  const row = recordId.match(/[:.]([0-9]+)$/)?.[1];
  return row ? `Import record ${String(row).padStart(2, "0")}` : `Import record ${numericCode(recordId)}`;
}

function humanize(value: string): string {
  return value.toLowerCase().replaceAll("_", " ").replace(/\b\w/g, character => character.toUpperCase());
}

function money(amountMinor: number, currency: string): string {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency }).format(amountMinor / 100);
}

function useLoad<T>(loader: () => Promise<T>, initial: T): [T, boolean, string, () => Promise<void>] {
  const [data, setData] = useState(initial);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    try { setData(await loader()); } catch (reason) { setError(message(reason)); }
    finally { setLoading(false); }
  }, [loader]);
  useEffect(() => { void refresh(); }, [refresh]);
  return [data, loading, error, refresh];
}

function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const authenticated = Boolean(session().token);
  return <div className="app-shell">
    <aside className={`sidebar ${open ? "open" : ""}`}>
      <div className="sidebar-top"><div className="brand"><span className="brand-mark"><ShieldCheck size={18}/></span><span>Finstack</span></div><button className="icon-btn mobile-only" onClick={() => setOpen(false)}><X size={18}/></button></div>
      <p className="nav-label">AUDIT OPERATIONS</p><nav>{navigation.map(([href,label,Icon]) => <Link key={href} href={href} onClick={() => setOpen(false)} className={`nav-item ${pathname.startsWith(href.slice(0,-1)) ? "active" : ""}`}><Icon size={17}/><span>{label}</span></Link>)}</nav>
      <div className="sidebar-footer"><span className={`status-dot ${authenticated ? "" : "offline"}`}/><div><strong>{authenticated ? "Authenticated" : "Local API mode"}</strong><small>{authenticated ? "ADMIN session" : "Login for audit activity"}</small></div></div>
    </aside>
    {open ? <button className="backdrop" onClick={() => setOpen(false)}/> : null}
    <div className="workspace"><header className="topbar"><button className="icon-btn mobile-only" onClick={() => setOpen(true)}><Menu size={19}/></button><label className="search"><Search size={16}/><input placeholder="Search audit records"/></label><Link className="profile" href="/login/"><span className="avatar">AR</span><span><strong>{authenticated ? "Administrator" : "Sign in"}</strong><small>{authenticated ? "Connected session" : "admin account"}</small></span></Link></header><main>{children}</main><footer><span>Finstack · Deterministic banking audit</span><span>Live API v1</span></footer></div>
  </div>;
}

function Heading({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <div className="page-heading"><div><span className="eyebrow">LIVE AUDIT PLATFORM</span><h1>{title}</h1><p>{description}</p></div>{action}</div>;
}

function State({ loading, error, empty }: { loading: boolean; error: string; empty?: boolean }) {
  if (loading) return <div className="card page-card">Loading authoritative data…</div>;
  if (error) return <div className="card page-card form-error">{error}</div>;
  if (empty) return <div className="card page-card">No records yet. Import a CSV to start the pipeline.</div>;
  return null;
}

function Dashboard() {
  const loader = useCallback(() => getMetrics(), []);
  const [data, loading, error] = useLoad<Metrics>(loader, { ingestion_source_records:0, canonical_transactions:0, duplicate_evidence:0, circular_findings:0, splitting_findings:0, case_count:0, activity_count:0 });
  return <><Heading title="Audit operations" description="Live counts from the composed backend runtime."/><State loading={loading} error={error}/>{!loading && !error ? <section className="metrics-grid">{[
    ["Source records", data.ingestion_source_records], ["Canonical transactions", data.canonical_transactions], ["Duplicate evidence", data.duplicate_evidence], ["Circular findings", data.circular_findings], ["Splitting findings", data.splitting_findings], ["Cases", data.case_count],
  ].map(([label,value]) => <article className="metric-card" key={label}><div className="metric-label"><span>{label}</span></div><strong>{value}</strong><p>Authoritative backend count</p></article>)}</section> : null}</>;
}

function Ingestion() {
  const [file,setFile]=useState<File|null>(null); const [source,setSource]=useState("internal"); const [job,setJob]=useState<IngestionJob|null>(null); const [error,setError]=useState(""); const [busy,setBusy]=useState(false);
  async function submit(event: FormEvent){event.preventDefault();if(!file)return;setBusy(true);setError("");try{setJob(await createIngestionJob(file,source));}catch(reason){setError(message(reason));}finally{setBusy(false)}}
  return <><Heading title="Import transactions" description="Accepted rows flow directly into canonicalization, duplicate resolution and detector snapshots."/><section className="ingestion-layout"><form className="card upload-card" onSubmit={submit}><label className="dropzone"><FileUp size={28}/><strong>{file?.name ?? "Choose a CSV ledger"}</strong><input type="file" accept=".csv,text/csv" onChange={e=>setFile(e.target.files?.[0]??null)}/></label><label className="field"><span>Source system</span><input value={source} onChange={e=>setSource(e.target.value)} required/></label><button className="primary-btn wide" disabled={!file||busy}>{busy?"Processing…":"Import and process"}</button>{error?<p className="form-error">{error}</p>:null}</form><aside className="card import-status"><h2>{job?.status ?? "Waiting for upload"}</h2>{job?<div className="status-grid"><span><small>Processed</small><strong>{job.processed_count}</strong></span><span><small>Accepted</small><strong>{job.accepted_count}</strong></span><span><small>Rejected</small><strong>{job.rejected_count}</strong></span><span><small>Duplicates</small><strong>{job.duplicate_count}</strong></span></div>:null}</aside></section></>;
}

function Transactions() {
  const loader=useCallback(()=>listTransactions(),[]); const [rows,loading,error]=useLoad<Transaction[]>(loader,[]);
  return <><Heading title="Canonical transactions" description="Economic events generated from accepted source rows."/><State loading={loading} error={error} empty={!rows.length}/>{rows.length?<Table headers={["Transaction","From / To","Amount","Date and time","Status"]} rows={rows.map(x=>[transactionLabel(x.transaction_reference,x.occurred_at),`${accountLabel(x.sender_account_id)} → ${accountLabel(x.receiver_account_id)}`,money(x.amount_minor,x.currency),new Date(x.occurred_at).toLocaleString(),humanize(x.status)])}/>:null}</>;
}

function Duplicates() {
  const loader=useCallback(()=>listDuplicates(),[]); const [rows,loading,error]=useLoad<DuplicateEvidence[]>(loader,[]);
  const candidates=rows.filter(x=>x.classification!=="NON_MATCH");
  return <><Heading title="Potential duplicate transactions" description="Records that require duplicate review."/><State loading={loading} error={error} empty={!candidates.length}/>{candidates.length?<Table headers={["First record","Compared record","Assessment","Confidence","Reason"]} rows={candidates.map(x=>[recordLabel(x.left_record_id),recordLabel(x.right_record_id),humanize(x.classification),`${x.score}%`,x.reasons.map(humanize).join(", ")])}/>:null}</>;
}

function Findings({ detector }: { detector?: "circular"|"splitting" }) {
  const loader=useCallback(()=>listFindings(),[]); const [rows,loading,error,refresh]=useLoad<Finding[]>(loader,[]); const [action,setAction]=useState("");
  const shown=detector?rows.filter(x=>x.type===`${detector.toUpperCase()==="CIRCULAR"?"CIRCULAR_FLOW":"SPLITTING_PATTERN"}`):rows;
  async function run(){if(!detector)return;setAction("Running…");try{const result=await runDetector(detector,"2020-01-01T00:00:00Z","2030-01-01T00:00:00Z");setAction(`${result.finding_count??0} findings · ${result.replayed?"replayed":"new run"}`);await refresh();}catch(reason){setAction(message(reason));}}
  async function makeCase(item:Finding){try{const value=await createCase([item.finding_id],item.type==="CIRCULAR_FLOW"?90:75);setAction(`Created ${value.case_code}`);}catch(reason){setAction(message(reason));}}
  return <><Heading title={detector?`${detector[0].toUpperCase()+detector.slice(1)} detector`:"Audit findings"} description="Reviewable findings produced by deterministic analysis." action={detector?<button className="primary-btn" onClick={run}><Network size={16}/>Run detector</button>:undefined}/>{action?<p>{action}</p>:null}<State loading={loading} error={error} empty={!shown.length}/>{shown.length?<Table headers={["Finding","Transactions involved","Status","Action"]} rows={shown.map(x=>[humanize(x.type),`${x.transaction_ids.length} linked transaction${x.transaction_ids.length===1?"":"s"}`,humanize(x.status),<button key={x.finding_id} className="secondary-btn" onClick={()=>makeCase(x)}>Create case</button>])}/>:null}</>;
}

function Reconciliation() {
  const [left,setLeft]=useState("internal"); const [right,setRight]=useState("clearing"); const [result,setResult]=useState<Record<string,number>|null>(null); const [error,setError]=useState(""); const [busy,setBusy]=useState(false);
  async function run(){setBusy(true);setResult(null);setError("");try{const value=await runReconciliation(left,right,"2020-01-01T00:00:00Z","2030-01-01T00:00:00Z");setResult(value.classification_counts??{});}catch(reason){setError(message(reason));}finally{setBusy(false)}}
  return <><Heading title="Ledger reconciliation" description="One-to-one comparison of two imported source systems."/><section className="card page-card"><div className="filter-row"><input value={left} onChange={e=>setLeft(e.target.value)} aria-label="Left source"/><input value={right} onChange={e=>setRight(e.target.value)} aria-label="Right source"/><button className="primary-btn" onClick={run} disabled={busy}>{busy?"Reconciling…":"Run reconciliation"}</button></div>{error?<p className="form-error">{error}</p>:null}{result?<Table headers={["Result","Transactions"]} rows={Object.entries(result).map(([classification,count])=>[humanize(classification),String(count)])}/>:null}</section></>;
}

function Cases() {
  const loader=useCallback(()=>listCases(),[]); const [rows,loading,error,refresh]=useLoad<AuditCase[]>(loader,[]); const [action,setAction]=useState("");
  async function claim(item:AuditCase){try{await claimCase(item);setAction(`${item.case_code} claimed`);await refresh();}catch(reason){setAction(message(reason));}}
  return <><Heading title="Audit cases" description="Priority cases with atomic claim protection."/><State loading={loading} error={error} empty={!rows.length}/>{action?<p>{action}</p>:null}{rows.length?<div className="card page-card"><Table headers={["Case","State","Priority","Assignee","Action"]} rows={rows.map(x=>[x.case_code,x.state,String(x.priority),x.assignee_id??"Unassigned",x.state==="QUEUED"?<button key={x.case_id} className="secondary-btn" onClick={()=>claim(x)}>Claim</button>:"—"])}/></div>:null}</>;
}

function Login() {
  const router=useRouter(); const [username,setUsername]=useState("admin"); const [password,setPassword]=useState("admin-password"); const [error,setError]=useState(""); const [busy,setBusy]=useState(false);
  async function submit(event:FormEvent){event.preventDefault();setBusy(true);setError("");try{await login(username,password);router.push("/dashboard/");}catch(reason){setError(message(reason));}finally{setBusy(false)}}
  return <><Heading title="Administrator sign in" description="Start an eight-hour server-side session."/><form className="card upload-card" onSubmit={submit}><label className="field"><span>Username</span><input value={username} onChange={e=>setUsername(e.target.value)}/></label><label className="field"><span>Password</span><input type="password" value={password} onChange={e=>setPassword(e.target.value)}/></label><button className="primary-btn wide" disabled={busy}><LogIn size={16}/>{busy?"Signing in…":"Sign in"}</button>{error?<p className="form-error">{error}</p>:null}</form></>;
}

function Table({headers,rows}:{headers:string[];rows:ReactNode[][]}) { return <div className="card page-card table-scroll"><table><thead><tr>{headers.map(x=><th key={x}>{x}</th>)}</tr></thead><tbody>{rows.map((row,i)=><tr key={i}>{row.map((cell,j)=><td key={j}>{cell}</td>)}</tr>)}</tbody></table></div>; }

export function AuditApp({ view }: { view: View }) {
  const content: Record<View,ReactNode> = { dashboard:<Dashboard/>, ingestion:<Ingestion/>, transactions:<Transactions/>, duplicates:<Duplicates/>, findings:<Findings/>, reconciliation:<Reconciliation/>, circular:<Findings detector="circular"/>, splitting:<Findings detector="splitting"/>, cases:<Cases/>, login:<Login/> };
  return <Shell>{content[view]}</Shell>;
}
