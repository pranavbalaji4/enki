"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useAppState } from "@/components/AppState";
import { Button, Chip, Markdown } from "@/components/ui";
import { api, type InsightOut } from "@/lib/api";

export default function InsightsPage() {
  const { refresh } = useAppState();
  const [tab, setTab] = useState<"new" | "all">("new");
  const [items, setItems] = useState<InsightOut[] | null>(null);

  const load = useCallback(async () => {
    setItems(await api.insights(tab === "new" ? "new" : null));
  }, [tab]);

  useEffect(() => {
    api.insights(tab === "new" ? "new" : null).then(setItems);
  }, [tab]);

  async function respond(id: number, action: "confirm" | "reject" | "dismiss", note: string) {
    await api.insightFeedback(id, action, note);
    await load();
    refresh();
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-6 py-8">
        <h1 className="font-serif text-3xl font-semibold">Insights</h1>
        <p className="mt-2 text-ink-soft">
          What Enki has noticed about how you learn. Your answers here are the strongest signal it gets — a confirmed pattern
          shapes every future explanation; a rejected one is dropped.
        </p>

        <div className="mt-6 flex gap-1 border-b border-line">
          {(["new", "all"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === t ? "border-accent text-ink" : "border-transparent text-ink-soft hover:text-ink"}`}
            >
              {t === "new" ? "New" : "All"}
            </button>
          ))}
        </div>

        <div className="mt-6 space-y-5">
          {items === null && <p className="text-ink-faint">Loading…</p>}
          {items?.length === 0 && (
            <p className="rounded-xl border border-dashed border-line p-6 text-center text-ink-soft">
              {tab === "new"
                ? "Nothing new. Finish a chat with “Wrap up” to get a recap; patterns appear once there’s enough evidence (a few sessions)."
                : "No insights yet."}
            </p>
          )}
          {items?.map((i) => <InsightCard key={i.id} insight={i} onRespond={respond} />)}
        </div>
      </div>
    </div>
  );
}

function InsightCard({
  insight: i,
  onRespond,
}: {
  insight: InsightOut;
  onRespond: (id: number, action: "confirm" | "reject" | "dismiss", note: string) => void;
}) {
  const [note, setNote] = useState("");
  const [showNote, setShowNote] = useState(false);
  const isPattern = i.kind === "pattern";
  const statusChip = { confirmed: ["accent", "You confirmed"], rejected: ["bad", "You rejected"], dismissed: ["none", "Dismissed"] } as const;
  const s = statusChip[i.status as keyof typeof statusChip];

  return (
    <article className={`rounded-xl border bg-panel p-5 ${isPattern ? "border-accent/50" : "border-line"}`}>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-ink-faint">
        <Chip t={isPattern ? "accent" : "none"}>{isPattern ? "Pattern" : "Session recap"}</Chip>
        <span>{i.scope}</span>
        {i.session_id && (
          <Link href={`/s/${i.session_id}`} className="hover:text-accent">
            open chat →
          </Link>
        )}
        {s && <Chip t={s[0]}>{s[1]}</Chip>}
      </div>
      <h2 className="font-serif text-xl font-semibold">{i.title}</h2>
      <div className="mt-1">
        <Markdown>{i.body}</Markdown>
      </div>

      {!isPattern && i.evidence.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm text-ink-soft">
          {i.evidence.map((e) => (
            <li key={e.id}>
              <span className="font-medium text-ink">{e.concept}</span> — <span className="font-mono text-xs">{e.path_summary}</span>
            </li>
          ))}
        </ul>
      )}

      {i.status === "new" && (
        <div className="mt-4">
          {showNote && (
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Add nuance — e.g. “only when I'm new to a topic”"
              rows={2}
              className="mb-2 w-full rounded-lg border border-line bg-paper p-2 text-sm outline-none focus:border-accent"
            />
          )}
          <div className="flex flex-wrap gap-2">
            {isPattern ? (
              <>
                <Button variant="primary" onClick={() => onRespond(i.id, "confirm", note)}>
                  Yes, that’s me
                </Button>
                <Button variant="danger" onClick={() => onRespond(i.id, "reject", note)}>
                  Not really
                </Button>
                {!showNote && <Button onClick={() => setShowNote(true)}>Add a note</Button>}
              </>
            ) : (
              <Button onClick={() => onRespond(i.id, "dismiss", "")}>Got it</Button>
            )}
          </div>
        </div>
      )}
    </article>
  );
}
