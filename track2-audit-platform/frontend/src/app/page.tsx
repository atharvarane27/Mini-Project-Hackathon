import Link from "next/link";
import { ShieldCheck, Activity, Cpu, ArrowRight } from "lucide-react";

export default function Home() {
  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 flex flex-col items-center justify-center p-6 sm:p-12">
      <div className="max-w-4xl w-full space-y-8 text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-sky-500/30 bg-sky-500/10 text-sky-400 text-xs font-medium tracking-wide">
          <ShieldCheck className="w-4 h-4" />
          Track 2 Platform Foundation Active (Phase P00)
        </div>

        <h1 className="text-4xl sm:text-6xl font-extrabold tracking-tight bg-gradient-to-r from-sky-400 via-indigo-300 to-teal-300 bg-clip-text text-transparent">
          AuditForge
        </h1>

        <p className="text-slate-400 max-w-2xl mx-auto text-base sm:text-lg">
          Concurrent Banking Audit, Record Resolution & Rule-Driven Workflow Platform.
          Deterministic custom in-memory engines, 3NF PostgreSQL persistence, and strict RBAC audit governance.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-4 text-left">
          <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/50 backdrop-blur">
            <Cpu className="w-6 h-6 text-sky-400 mb-2" />
            <h3 className="font-semibold text-slate-200">Custom In-RAM Engines</h3>
            <p className="text-xs text-slate-400 mt-1">
              Phonetic inverted index, AST rule evaluator, synchronized binary heap, and DAG cycle validator.
            </p>
          </div>

          <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/50 backdrop-blur">
            <Activity className="w-6 h-6 text-emerald-400 mb-2" />
            <h3 className="font-semibold text-slate-200">Durable Outbox</h3>
            <p className="text-xs text-slate-400 mt-1">
              Supabase PostgreSQL primary DB with transactional outbox and worker recovery guarantees.
            </p>
          </div>

          <div className="p-4 rounded-xl border border-slate-800 bg-slate-900/50 backdrop-blur">
            <ShieldCheck className="w-6 h-6 text-amber-400 mb-2" />
            <h3 className="font-semibold text-slate-200">Audit Immutability</h3>
            <p className="text-xs text-slate-400 mt-1">
              Append-only audit ledger with atomic state transitions and strict role-based access control.
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-center gap-4 pt-6">
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-medium text-sm transition-colors shadow-lg shadow-sky-600/20"
          >
            Access Dashboard
            <ArrowRight className="w-4 h-4" />
          </Link>
          <a
            href="/api/v1/health"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg border border-slate-700 bg-slate-900 hover:bg-slate-800 text-slate-300 font-medium text-sm transition-colors"
          >
            API Health Endpoint
          </a>
        </div>
      </div>
    </main>
  );
}
