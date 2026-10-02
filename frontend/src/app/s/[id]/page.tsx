"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { pathOf, useAppState } from "@/components/AppState";
import { Button, Chip, Markdown, STRATEGY_LABEL, VERDICT_LABEL, label, tone } from "@/components/ui";
import { api, streamMessage, type AnnotationOut, type EpisodeOut, type SessionOut } from "@/lib/api";

type Pending = { user: string; reply: string } | null;

export default function SessionPage() {
  const { id } = useParams<{ id: string }>();
  return <SessionView key={id} sessionId={Number(id)} />;
}

function SessionView({ sessionId }: { sessionId: number }) {
  const { nodes, refresh: refreshApp } = useAppState();
  const [data, setData] = useState<SessionOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending>(null);
  const [input, setInput] = useState("");
  const [lens, setLens] = useState(true);
  const [showReview, setShowReview] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.session(sessionId));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [sessionId]);

  useEffect(() => {
    api.session(sessionId).then(setData, (e: Error) => setError(e.message));
  }, [sessionId]);

  // Background analysis (tagging, evaluation, review) lands a few seconds later; poll while it runs.
  const busy = !!data && (data.pending_jobs > 0 || data.node.status === "reviewing");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(async () => {
      const next = await api.session(sessionId).catch(() => null);
      if (!next) return;
      setData(next);
      if (next.pending_jobs === 0 && next.node.status !== "reviewing") refreshApp();
    }, 2000);
    return () => clearInterval(t);
  }, [busy, sessionId, refreshApp]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [data?.messages.length, pending?.reply]);

  const anns = useMemo(() => new Map((data?.annotations ?? []).map((a) => [a.message_id, a])), [data]);
  const winners = useMemo(() => {
    const m = new Map<number, EpisodeOut>();
    for (const e of data?.episodes ?? []) if (e.winning_message_id && e.outcome !== "not_yet") m.set(e.winning_message_id, e);
    return m;
  }, [data]);

  async function send() {
    const text = input.trim();
    if (!text || pending) return;
    setInput("");
    setError(null);
    setPending({ user: text, reply: "" });
    await streamMessage(sessionId, text, (ev) => {
      if (ev.type === "delta") setPending((p) => (p ? { ...p, reply: p.reply + ev.text } : p));
      if (ev.type === "error") {
        setError(ev.message);
        setInput(text);
      }
    }).catch((e) => {
      setError((e as Error).message);
      setInput(text);
    });
    await load();
    setPending(null);
    refreshApp();
  }

  async function wrapUp() {
    await api.wrapUp(sessionId);
    setShowReview(true);
    await load();
    refreshApp();
  }

  const crumbs = pathOf(nodes, sessionId);
  const messages = data?.messages ?? [];
  const reviewed = data?.node.status === "reviewed";

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-line bg-panel px-6 py-3">
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs text-ink-faint">
            {crumbs.slice(0, -1).map((c) => (
              <span key={c.id}>
                <Link href={`/n/${c.id}`} className="hover:text-accent hover:underline">
                  {c.title}
                </Link>
                <span className="mx-1.5">/</span>
              </span>
            ))}
          </div>
          <h1 className="truncate font-serif text-xl font-semibold">{data?.node.title ?? "…"}</h1>
        </div>
        <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-ink-soft" title="Show how each explanation was built and how it landed">
          <input type="checkbox" checked={lens} onChange={(e) => setLens(e.target.checked)} className="accent-[var(--accent)]" />
          Learning lens
        </label>
        {busy && <span className="text-xs text-ink-faint">{data?.node.status === "reviewing" ? "Reviewing session…" : "Analyzing…"}</span>}
        <Button
          variant="primary"
          onClick={wrapUp}
          disabled={!messages.length || !!pending || data?.node.status === "reviewing"}
          title="Review this session: find where things clicked and update how Enki teaches you"
        >
          {reviewed ? "Re-review" : "Wrap up"}
        </Button>
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-6 py-6">
          {reviewed && data && data.episodes.length > 0 && (
            <ReviewPanel data={data} open={showReview} onToggle={() => setShowReview((v) => !v)} />
          )}

          {!messages.length && !pending && data && <EmptyState path={data.path} />}

          <div className="space-y-6">
            {messages.map((m) =>
              m.role === "user" ? (
                <UserBubble key={m.id} text={m.content} />
              ) : (
                <TutorMessage key={m.id} text={m.content} ann={anns.get(m.id)} lens={lens} winner={winners.get(m.id)} />
              ),
            )}
            {pending && (
              <>
                <UserBubble text={pending.user} />
                <TutorMessage text={pending.reply || "…"} lens={false} />
              </>
            )}
          </div>

          {data && data.failed_jobs.length > 0 && (
            <p className="mt-6 rounded-lg bg-mid-soft p-3 text-xs text-mid">
              Some background analysis failed: {data.failed_jobs[0]}
            </p>
          )}
          <div ref={bottomRef} className="h-4" />
        </div>
      </div>

      <div className="border-t border-line bg-panel px-6 py-4">
        <div className="mx-auto max-w-3xl">
          {error && <p className="mb-2 rounded-md bg-bad-soft px-3 py-2 text-sm text-bad">{error}</p>}
          <div className="flex items-end gap-2 rounded-xl border border-line bg-paper p-2 focus-within:border-accent">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              rows={Math.min(6, Math.max(1, input.split("\n").length))}
              placeholder="Ask anything — and say so when it doesn't make sense. That's the signal Enki learns from."
              className="max-h-40 flex-1 resize-none bg-transparent px-2 py-1.5 text-[15px] outline-none placeholder:text-ink-faint"
            />
            <Button variant="primary" onClick={send} disabled={!input.trim() || !!pending}>
              Send
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function EmptyState({ path }: { path: string }) {
  return (
    <div className="mx-auto mt-10 max-w-md text-center text-ink-soft">
      <p className="font-serif text-lg text-ink">{path}</p>
      <p className="mt-2 text-sm">
        Ask your first question. Reply honestly — “I don’t get it”, “so it’s like…?”, “why?” — Enki reads those replies to
        learn which explanations work for you. When you’re done, press <strong>Wrap up</strong>.
      </p>
    </div>
  );
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-accent-soft px-4 py-2.5 text-[15px]">{text}</div>
    </div>
  );
}

function TutorMessage({ text, ann, lens, winner }: { text: string; ann?: AnnotationOut; lens: boolean; winner?: EpisodeOut }) {
  return (
    <div className={winner ? "-mx-4 rounded-xl border border-accent/40 bg-accent-soft/40 px-4 py-2" : ""}>
      {winner && (
        <div className="mb-1 text-xs font-semibold text-accent" title={winner.why_it_clicked}>
          ✦ This is where “{winner.concept}” clicked
        </div>
      )}
      <Markdown>{text}</Markdown>
      {lens && ann && <Lens ann={ann} />}
    </div>
  );
}

function Lens({ ann }: { ann: AnnotationOut }) {
  const t = tone(ann.understanding);
  const detail = [ann.reasoning, ann.referenced_part && `You picked up on: “${ann.referenced_part}”`].filter(Boolean).join("\n");
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-dashed border-line pt-2">
      {ann.concept && <span className="mr-1 text-xs text-ink-faint">{ann.concept}</span>}
      {ann.strategies.map((s) => (
        <Chip key={s}>{label(s, STRATEGY_LABEL)}</Chip>
      ))}
      {ann.ordering && ann.ordering !== "single_mode" && <Chip>{label(ann.ordering, STRATEGY_LABEL)}</Chip>}
      <span className="mx-1 text-ink-faint">→</span>
      {ann.verdict ? (
        <>
          {ann.level_probs && <LevelBar probs={ann.level_probs} />}
          <Chip t={t} title={detail}>
            {label(ann.verdict, VERDICT_LABEL)}
            {ann.confidence != null && ann.confidence < 0.45 ? " ?" : ""}
          </Chip>
          {(ann.signals?.reused_explanation ?? 0) >= 0.6 && (
            <Chip t="accent" title="You reused an analogy, example or wording from this reply">
              Reused it
            </Chip>
          )}
          {(ann.signals?.frustrated ?? 0) >= 0.6 && <Chip t="bad">Frustrated</Chip>}
          {ann.evaluator === "jev" && <span className="text-[11px] text-ink-faint">via Jev</span>}
        </>
      ) : (
        <span className="text-xs text-ink-faint">your next reply will tell</span>
      )}
    </div>
  );
}

const LEVELS = [
  { name: "Not understood", cls: "bg-bad" },
  { name: "Iffy", cls: "bg-mid" },
  { name: "Understood", cls: "bg-good" },
];

/** Jev's probability for each understanding level, as a stacked bar (understood on the left). */
function LevelBar({ probs }: { probs: number[] }) {
  const order = [2, 1, 0];
  const title = order.map((i) => `${LEVELS[i].name}: ${Math.round((probs[i] ?? 0) * 100)}%`).join(" · ");
  const top = probs.indexOf(Math.max(...probs));
  return (
    <span className="inline-flex items-center gap-1.5" title={title}>
      <span className="flex h-2 w-16 overflow-hidden rounded-full bg-sunken">
        {order.map((i) => (
          <span key={i} className={LEVELS[i].cls} style={{ width: `${(probs[i] ?? 0) * 100}%` }} />
        ))}
      </span>
      <span className="text-xs text-ink-soft">
        {LEVELS[top].name} {Math.round(probs[top] * 100)}%
      </span>
    </span>
  );
}

function ReviewPanel({ data, open, onToggle }: { data: SessionOut; open: boolean; onToggle: () => void }) {
  const outcomeTone = { clicked: "good", partial: "mid", not_yet: "bad" } as const;
  const outcomeLabel = { clicked: "Clicked", partial: "Partly", not_yet: "Not yet" } as const;
  return (
    <section className="mb-8 rounded-xl border border-line bg-panel">
      <button onClick={onToggle} className="flex w-full items-center justify-between px-4 py-3 text-left">
        <span className="text-sm font-semibold">Session review · {data.episodes.length} concept{data.episodes.length === 1 ? "" : "s"}</span>
        <span className="text-xs text-ink-faint">{open ? "Hide" : "Show"}</span>
      </button>
      {open && (
        <div className="space-y-4 border-t border-line px-4 py-4">
          {data.summary && <p className="text-sm text-ink-soft">{data.summary}</p>}
          {data.episodes.map((e) => (
            <div key={e.id} className="text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{e.concept}</span>
                <Chip t={outcomeTone[e.outcome as keyof typeof outcomeTone] ?? "none"}>
                  {outcomeLabel[e.outcome as keyof typeof outcomeLabel] ?? e.outcome}
                </Chip>
              </div>
              <p className="mt-1 font-mono text-xs text-ink-soft">{e.path_summary}</p>
              {e.why_it_clicked && <p className="mt-1 text-ink-soft">{e.why_it_clicked}</p>}
              {e.prompting_moves.length > 0 && (
                <p className="mt-1 text-xs text-ink-faint">What you did that helped: {e.prompting_moves.join(" · ")}</p>
              )}
            </div>
          ))}
          <Link href="/insights" className="inline-block text-sm text-accent hover:underline">
            See your insights →
          </Link>
        </div>
      )}
    </section>
  );
}
