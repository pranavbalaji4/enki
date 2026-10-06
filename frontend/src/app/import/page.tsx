"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { runIsActive, useAppState } from "@/components/AppState";
import { STAGE_LABEL } from "@/components/Sidebar";
import { Button, ErrorNote, Page } from "@/components/ui";
import { api, type Estimate, type ImportOut, type RunOut } from "@/lib/api";

const STAGES = ["classify", "topics", "turns", "review", "profile"];
const STAGE_DETAIL: Record<string, string> = {
  classify: "Which chats were about learning something, and what they were about",
  topics: "Grouping them into subjects and topics",
  turns: "Judging each of Claude’s replies from the message you sent next",
  review: "Finding where things clicked in each chat, and what did it",
  profile: "Summarizing each topic and writing your profile",
};

export default function ImportPage() {
  const { run, watchRun, refresh, nodes, dataVersion } = useAppState();
  const [uploaded, setUploaded] = useState<ImportOut | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scope, setScope] = useState<"all" | "recent">("all");
  const [recent, setRecent] = useState(25);
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const limit = scope === "recent" ? Math.max(1, recent) : undefined;
  useEffect(() => {
    api.estimate(limit).then(setEstimate, () => setEstimate(null));
  }, [limit, uploaded, dataVersion]);

  async function upload(file: File) {
    setUploading(true);
    setError(null);
    try {
      setUploaded(await api.uploadExport(file));
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  }

  async function start() {
    setError(null);
    try {
      watchRun(await api.startAnalysis(limit));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const leftOut = useMemo(() => nodes.filter((n) => n.kind === "session" && n.is_learning === false), [nodes]);
  const active = runIsActive(run);
  const pending = estimate?.chats ?? 0;

  return (
    <Page>
      <h1 className="font-serif text-3xl font-medium tracking-tight">Import your Claude chats</h1>
      <p className="mt-3 max-w-[62ch] text-ink-soft">
        Enki works from the data export claude.ai gives you. Your chats stay on this computer; they’re only sent to the
        Anthropic API, with your own key, to be analyzed.
      </p>

      <ol className="mt-10 space-y-10">
        <Step n={1} title="Request your export from claude.ai">
          <p className="text-ink-soft">
            In claude.ai, open <strong className="font-medium text-ink">Settings</strong>, then{" "}
            <strong className="font-medium text-ink">Privacy</strong>, and choose{" "}
            <strong className="font-medium text-ink">Export data</strong>. You’ll get an email with a download link to a
            ZIP file. It can take a few minutes to arrive.
          </p>
        </Step>

        <Step n={2} title="Upload the ZIP">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              const f = e.dataTransfer.files[0];
              if (f) upload(f);
            }}
            className={`rounded-xl border border-dashed px-5 py-8 text-center transition ${
              dragging ? "border-accent bg-accent-soft" : "border-line bg-sunken"
            }`}
          >
            <p className="text-ink-soft">{uploading ? "Reading your export…" : "Drop the ZIP here, or"}</p>
            <Button className="mt-3" onClick={() => fileRef.current?.click()} disabled={uploading}>
              Choose file
            </Button>
            <input
              ref={fileRef}
              type="file"
              accept=".zip,.json,application/zip,application/json"
              className="sr-only"
              aria-label="Export file"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload(f);
                e.target.value = "";
              }}
            />
          </div>
          {uploaded && (
            <p className="mt-3 text-sm text-ink-soft">
              {uploaded.new} new chat{uploaded.new === 1 ? "" : "s"}, {uploaded.updated} updated, {uploaded.unchanged}{" "}
              already imported
              {uploaded.empty > 0 && `, ${uploaded.empty} empty and skipped`}.
            </p>
          )}
        </Step>

        <Step n={3} title="Check the cost and analyze">
          {pending === 0 && !active ? (
            <p className="text-ink-soft">
              {uploaded || nodes.some((n) => n.kind === "session")
                ? "Every imported chat is analyzed."
                : "Nothing to analyze yet. Upload your export first."}
            </p>
          ) : (
            !active && (
              <>
                <fieldset className="space-y-2 text-ink-soft">
                  <legend className="sr-only">Which chats to analyze</legend>
                  <label className="flex items-center gap-2">
                    <input type="radio" checked={scope === "all"} onChange={() => setScope("all")} className="accent-[var(--accent)]" />
                    All waiting chats
                  </label>
                  <label className="flex flex-wrap items-center gap-2">
                    <input type="radio" checked={scope === "recent"} onChange={() => setScope("recent")} className="accent-[var(--accent)]" />
                    Only the most recent
                    <input
                      type="number"
                      min={1}
                      value={recent}
                      aria-label="Number of recent chats"
                      onFocus={() => setScope("recent")}
                      onChange={(e) => setRecent(Number(e.target.value) || 1)}
                      className="tabular w-20 rounded-md border border-line bg-sunken px-2 py-1 text-ink"
                    />
                    chats, to try it out first
                  </label>
                </fieldset>
                {estimate && (
                  <div className="mt-5 flex flex-wrap items-end gap-x-10 gap-y-3">
                    <Figure label="Chats" value={String(estimate.chats)} />
                    <Figure label="Claude replies to read" value={String(estimate.turns)} />
                    <Figure label="Estimated cost, at most" value={`$${estimate.usd.toFixed(2)}`} />
                  </div>
                )}
                <p className="mt-3 max-w-[62ch] text-sm text-ink-faint">
                  An upper bound: it assumes every chat is a learning chat. Chats that turn out to be tasks (an email, a
                  quick lookup) stop after the first, cheapest step.
                </p>
                <Button variant="primary" className="mt-5" onClick={start} disabled={!estimate?.chats}>
                  Analyze {estimate?.chats ?? ""} chat{estimate?.chats === 1 ? "" : "s"}
                </Button>
              </>
            )
          )}
          {run && (active || run.status === "failed" || run.status === "done") && <Progress run={run} />}
        </Step>
      </ol>

      {error && (
        <div className="mt-8">
          <ErrorNote>{error}</ErrorNote>
        </div>
      )}

      {leftOut.length > 0 && (
        <section className="mt-16">
          <h2 className="border-b border-line pb-2 font-serif text-lg font-semibold">
            Left out as tasks <span className="tabular text-sm font-normal text-ink-faint">{leftOut.length}</span>
          </h2>
          <p className="mt-2 text-sm text-ink-faint">
            These didn’t look like learning. Open one and choose “Include in my profile” if that’s wrong.
          </p>
          <ul className="mt-3 columns-1 gap-8 text-sm sm:columns-2">
            {leftOut.map((n) => (
              <li key={n.id} className="break-inside-avoid py-1">
                <Link href={`/chats/${n.id}`} className="text-ink-soft hover:text-accent">
                  {n.title}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </Page>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <li className="grid grid-cols-[2rem_1fr] gap-x-3">
      <span className="tabular font-serif text-2xl leading-7 text-ink-faint">{n}</span>
      <div>
        <h2 className="font-serif text-xl font-semibold leading-7">{title}</h2>
        <div className="mt-3">{children}</div>
      </div>
    </li>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-ink-faint">{label}</p>
      <p className="tabular font-serif text-3xl">{value}</p>
    </div>
  );
}

function Progress({ run }: { run: RunOut }) {
  const current = STAGES.indexOf(run.stage);
  const done = run.status === "done";
  const c = run.counts;
  return (
    <div className="mt-6 rounded-xl border border-line bg-sunken p-5">
      <p className="font-medium">
        {done
          ? `Analyzed ${run.chats} chat${run.chats === 1 ? "" : "s"}`
          : run.status === "failed"
            ? "The analysis stopped"
            : `Analyzing ${run.chats} chat${run.chats === 1 ? "" : "s"}`}
      </p>
      <ul className="mt-4 space-y-3">
        {STAGES.map((s, i) => {
          const state = done || i < current ? "done" : i === current ? (run.status === "failed" ? "failed" : "now") : "later";
          return (
            <li key={s} className="grid grid-cols-[1rem_1fr] gap-x-3">
              <span
                aria-hidden
                className={`mt-1.5 h-2 w-2 rounded-full ${
                  state === "done" ? "bg-good" : state === "now" ? "bg-accent" : state === "failed" ? "bg-bad" : "bg-line"
                }`}
              />
              <div>
                <p className={`text-sm ${state === "later" ? "text-ink-faint" : "text-ink"}`}>
                  {STAGE_LABEL[s]}
                  {state === "now" && run.stage_total > 0 && (
                    <span className="tabular text-ink-faint">
                      {" "}
                      {run.stage_done} of {run.stage_total}
                    </span>
                  )}
                </p>
                {state === "now" && (
                  <>
                    <p className="text-xs text-ink-faint">{STAGE_DETAIL[s]}</p>
                    {run.stage_total > 0 && (
                      <span className="mt-2 block h-1 overflow-hidden rounded-full bg-panel">
                        <span
                          className="block h-full bg-accent transition-[width] duration-500"
                          style={{ width: `${(run.stage_done / run.stage_total) * 100}%` }}
                        />
                      </span>
                    )}
                  </>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {(c.learning != null || c.reviewed != null) && (
        <p className="mt-4 text-sm text-ink-soft">
          {c.learning ?? 0} learning chat{c.learning === 1 ? "" : "s"}, {c.skipped ?? 0} left out as tasks,{" "}
          {c.turns ?? 0} replies read, {c.reviewed ?? 0} chats reviewed
          {c.failed ? `, ${c.failed} step${c.failed === 1 ? "" : "s"} failed` : ""}.
        </p>
      )}
      {run.error && (
        <div className="mt-3">
          <ErrorNote>{run.error}</ErrorNote>
        </div>
      )}
      {run.errors.length > 0 && (
        <details className="mt-3 text-sm text-ink-faint">
          <summary className="cursor-pointer">What failed</summary>
          <ul className="mt-2 space-y-1">
            {run.errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </details>
      )}
      {done && (
        <Link href="/" className="mt-4 inline-block text-sm text-accent hover:underline">
          See your insights
        </Link>
      )}
    </div>
  );
}
