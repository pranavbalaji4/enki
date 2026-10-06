"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useAppState } from "@/components/AppState";
import {
  Button,
  Chip,
  ErrorNote,
  LEVELS,
  LandingBar,
  Markdown,
  STRATEGY_LABEL,
  VERDICT_LABEL,
  formatDate,
  label,
  topLevel,
} from "@/components/ui";
import { api, type AnnotationOut, type ChatOut, type EpisodeOut } from "@/lib/api";

export default function ChatPage() {
  const { id } = useParams<{ id: string }>();
  const { dataVersion, refresh } = useAppState();
  const [data, setData] = useState<ChatOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.chat(Number(id)).then(
      (d) => {
        setData(d);
        setError(null);
      },
      (e: Error) => setError(e.message),
    );
  }, [id, dataVersion]);

  // Links like /chats/3#m42 point at one reply; jump there once it has rendered.
  useEffect(() => {
    if (!data || !window.location.hash) return;
    document.getElementById(window.location.hash.slice(1))?.scrollIntoView({ block: "center" });
  }, [data]);

  const anns = useMemo(() => new Map((data?.annotations ?? []).map((a) => [a.message_id, a])), [data]);
  const winners = useMemo(() => {
    const m = new Map<number, EpisodeOut>();
    for (const e of data?.episodes ?? []) if (e.winning_message_id && e.outcome !== "not_yet") m.set(e.winning_message_id, e);
    return m;
  }, [data]);

  async function toggleLearning() {
    if (!data) return;
    const chat = await api.setLearning(data.chat.id, !data.chat.is_learning);
    setData({ ...data, chat });
    refresh();
  }

  if (error)
    return (
      <div className="p-8">
        <ErrorNote>{error}</ErrorNote>
      </div>
    );
  if (!data) return null;
  const c = data.chat;

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-5 py-8 md:px-10 md:py-12">
        <nav className="text-sm text-ink-faint" aria-label="Breadcrumb">
          {data.breadcrumbs.length ? (
            data.breadcrumbs.map((b, i) => (
              <span key={b.id}>
                {i > 0 && <span className="mx-2">/</span>}
                <Link href={`/topics/${b.id}`} className="hover:text-accent">
                  {b.title}
                </Link>
              </span>
            ))
          ) : (
            <span>Not in a topic</span>
          )}
        </nav>
        <h1 className="mt-2 font-serif text-3xl font-medium tracking-tight">{c.title}</h1>
        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-ink-faint">
          <span>{formatDate(c.started_at)}</span>
          {data.claude_url && (
            <a href={data.claude_url} target="_blank" rel="noreferrer" className="text-accent hover:underline">
              Open in claude.ai
            </a>
          )}
          <StatusNote status={c.status} isLearning={c.is_learning} />
          {c.is_learning != null && (
            <Button onClick={toggleLearning} className="px-2 py-0.5 text-xs">
              {c.is_learning ? "Leave out of my profile" : "Include in my profile"}
            </Button>
          )}
        </div>

        {c.judged_turns > 0 && (
          <div className="mt-6">
            <LandingBar mix={c.mix} className="h-2" />
            <p className="mt-1.5 text-xs text-ink-faint">
              {c.judged_turns} of Claude’s replies judged in this chat
            </p>
          </div>
        )}

        {(data.summary || data.episodes.length > 0) && <Review data={data} />}

        <div className="mt-10 space-y-8">
          {data.messages.map((m) =>
            m.role === "user" ? (
              <div key={m.id} id={`m${m.id}`} className="flex justify-end">
                <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-panel px-4 py-2.5 text-[15px] leading-relaxed">
                  {m.content}
                </div>
              </div>
            ) : (
              <Reply key={m.id} id={m.id} text={m.content} ann={anns.get(m.id)} winner={winners.get(m.id)} />
            ),
          )}
        </div>
      </div>
    </div>
  );
}

function StatusNote({ status, isLearning }: { status: string; isLearning: boolean | null }) {
  if (status === "analyzed") return null;
  const text =
    status === "skipped" || isLearning === false
      ? "Not counted: this looked like a task, not learning"
      : status === "failed"
        ? "Analysis failed; it will be retried on the next run"
        : "Not analyzed yet";
  return <span>{text}</span>;
}

function Review({ data }: { data: ChatOut }) {
  const tone = { clicked: "good", partial: "mid", not_yet: "bad" } as const;
  const outcome = { clicked: "Clicked", partial: "Partly", not_yet: "Not yet" } as const;
  return (
    <section className="mt-8 border-l-2 border-accent pl-5">
      {data.summary && <p className="font-serif leading-relaxed text-ink-soft">{data.summary}</p>}
      {data.episodes.length > 0 && (
        <ul className="mt-4 space-y-4">
          {data.episodes.map((e) => (
            <li key={e.id} className="text-sm">
              <span className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{e.concept}</span>
                <Chip t={tone[e.outcome as keyof typeof tone] ?? "none"}>
                  {outcome[e.outcome as keyof typeof outcome] ?? e.outcome}
                </Chip>
              </span>
              <span className="mt-1 block text-ink-soft">{e.path_summary}</span>
              {e.why_it_clicked && <span className="mt-1 block text-ink-faint">{e.why_it_clicked}</span>}
              {e.prompting_moves.length > 0 && (
                <span className="mt-1 block text-ink-faint">What you did that helped: {e.prompting_moves.join("; ")}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Reply({ id, text, ann, winner }: { id: number; text: string; ann?: AnnotationOut; winner?: EpisodeOut }) {
  return (
    <div id={`m${id}`} className={winner ? "-ml-5 border-l-2 border-good pl-[18px]" : ""}>
      {winner && (
        <p className="mb-1 text-sm font-medium text-good" title={winner.why_it_clicked}>
          Where “{winner.concept}” clicked
        </p>
      )}
      <Markdown>{text}</Markdown>
      {ann ? <Landing ann={ann} /> : <p className="mt-2 text-xs text-ink-faint">Not analyzed yet</p>}
    </div>
  );
}

/** How one reply landed: the three probabilities, the verdict behind them, and who judged it. */
function Landing({ ann }: { ann: AnnotationOut }) {
  const [open, setOpen] = useState(false);
  if (ann.verdict === "no_signal" || !ann.verdict) {
    return (
      <p className="mt-3 text-xs text-ink-faint">
        The chat ended on this reply, so there’s no next message to judge it by.
      </p>
    );
  }
  const probs = ann.level_probs;
  const top = probs ? topLevel(probs) : null;
  const source = ann.evaluator === "jev" ? "Jev" : ann.evaluator === "fake" ? "Offline estimate" : "Claude’s estimate";
  return (
    <div className="mt-3 rounded-lg border border-line bg-sunken/60">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2 text-left text-sm"
      >
        {probs && top && (
          <>
            <LandingBar probs={probs} className="h-1.5 w-24" />
            <span className={`font-medium ${top.text}`}>
              {top.name} <span className="tabular">{Math.round((probs[top.probIndex] ?? 0) * 100)}%</span>
            </span>
          </>
        )}
        <span className="text-ink-soft">{label(ann.verdict, VERDICT_LABEL)}</span>
        {(ann.signals?.reused_explanation ?? 0) >= 0.6 && <Chip t="accent">You reused its wording</Chip>}
        {(ann.signals?.frustrated ?? 0) >= 0.6 && <Chip t="bad">Frustrated</Chip>}
        <span className="ml-auto text-xs text-ink-faint">{source}</span>
      </button>
      {open && (
        <div className="space-y-2 border-t border-line px-3 py-3 text-sm">
          {probs && (
            <p className="tabular flex flex-wrap gap-x-5 text-ink-soft">
              {LEVELS.map((l) => (
                <span key={l.key}>
                  <span className={l.text}>{Math.round((probs[l.probIndex] ?? 0) * 100)}%</span> {l.name.toLowerCase()}
                </span>
              ))}
            </p>
          )}
          {ann.reasoning && <p className="text-ink-soft">{ann.reasoning}</p>}
          {ann.referenced_part && <p className="text-ink-faint">You picked up on: “{ann.referenced_part}”</p>}
          {ann.strategies.length > 0 && (
            <p className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-ink-faint">How it explained</span>
              {ann.strategies.map((s) => (
                <Chip key={s}>{label(s, STRATEGY_LABEL)}</Chip>
              ))}
              {ann.ordering && ann.ordering !== "single_mode" && <Chip>{label(ann.ordering, STRATEGY_LABEL)}</Chip>}
            </p>
          )}
          {ann.confidence != null && (
            <p className="text-xs text-ink-faint">
              Judge’s confidence {Math.round(ann.confidence * 100)}%
              {ann.evaluator !== "jev" && ". Claude’s probabilities are its own estimate, not calibrated."}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
