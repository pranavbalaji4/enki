"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useAppState } from "@/components/AppState";
import { Button, Chip, ConfidenceBar, Markdown, STRATEGY_LABEL, label } from "@/components/ui";
import { api, type ProfileEditOut, type ProfileOut } from "@/lib/api";

export default function ProfilePage() {
  const { id } = useParams<{ id: string }>();
  return <ProfileView key={id} nodeId={Number(id)} />;
}

function ProfileView({ nodeId }: { nodeId: number }) {
  const { nodes } = useAppState();
  const [data, setData] = useState<ProfileOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<ProfileEditOut | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.profile(nodeId));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [nodeId]);

  useEffect(() => {
    api.profile(nodeId).then(setData, (e: Error) => setError(e.message));
  }, [nodeId]);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      setResult(await api.editProfile(nodeId, draft));
      setEditing(false);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const children = nodes.filter((n) => (nodeId === 0 ? n.parent_id == null : n.parent_id === nodeId));

  if (error && !data) return <p className="p-8 text-bad">{error}</p>;
  if (!data) return <p className="p-8 text-ink-faint">Loading…</p>;

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl px-6 py-8">
        <p className="text-xs uppercase tracking-wider text-ink-faint">{nodeId === 0 ? "Everywhere" : "Folder"}</p>
        <h1 className="font-serif text-3xl font-semibold">{data.title}</h1>
        {data.summary && <p className="mt-3 whitespace-pre-wrap text-[15px] leading-relaxed text-ink-soft">{data.summary}</p>}

        {children.length > 0 && (
          <div className="mt-5 flex flex-wrap gap-2">
            {children.map((c) => (
              <Link
                key={c.id}
                href={c.kind === "session" ? `/s/${c.id}` : `/n/${c.id}`}
                className="rounded-lg border border-line bg-panel px-3 py-1.5 text-sm hover:border-accent"
              >
                {c.kind === "folder" ? "▸ " : c.status === "reviewed" ? "✦ " : "· "}
                {c.title}
              </Link>
            ))}
          </div>
        )}

        {/* ---- editable profile ---- */}
        <section className="mt-10">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-ink-soft">How I learn here</h2>
            {!editing && (
              <Button
                onClick={() => {
                  setDraft(data.markdown);
                  setEditing(true);
                  setResult(null);
                }}
              >
                ✎ Edit
              </Button>
            )}
          </div>

          {result && (
            <div className="mb-4 rounded-xl border border-accent/40 bg-accent-soft/50 p-4 text-sm">
              <p className="font-medium">{result.understood}</p>
              {result.ops.length > 0 && (
                <ul className="mt-2 list-disc pl-5 text-ink-soft">
                  {result.ops.map((o, i) => (
                    <li key={i}>{o}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {editing ? (
            <div className="rounded-xl border border-line bg-panel p-4">
              <p className="mb-2 text-xs text-ink-faint">
                Edit freely: delete lines that are wrong, reword them, or add your own (“Diagrams help me with anything spatial”).
                Enki will tell you how it read your changes.
              </p>
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={Math.max(8, draft.split("\n").length + 2)}
                className="w-full resize-y rounded-lg border border-line bg-paper p-3 font-mono text-[13px] leading-relaxed outline-none focus:border-accent"
              />
              {error && <p className="mt-2 text-sm text-bad">{error}</p>}
              <div className="mt-3 flex gap-2">
                <Button variant="primary" onClick={save} disabled={saving}>
                  {saving ? "Interpreting…" : "Save"}
                </Button>
                <Button onClick={() => setEditing(false)} disabled={saving}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <div className="rounded-xl border border-line bg-panel px-5 py-3">
              <Markdown>{data.markdown}</Markdown>
            </div>
          )}
        </section>

        {/* ---- evidence ---- */}
        {data.patterns.length > 0 && (
          <section className="mt-10">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-ink-soft">The evidence</h2>
            <div className="divide-y divide-line rounded-xl border border-line bg-panel">
              {data.patterns.map((p) => (
                <div key={p.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-[15px]">{p.claim}</p>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      <Chip>{label(p.strategy, STRATEGY_LABEL)}</Chip>
                      {p.concept_type && <Chip>{p.concept_type.replace(/_/g, " ")}</Chip>}
                      {(p.user_status === "confirmed" || p.source === "user") && <Chip t="accent">confirmed by you</Chip>}
                      {p.user_status === "edited" && <Chip t="accent">edited by you</Chip>}
                    </div>
                  </div>
                  <div className="text-right">
                    <ConfidenceBar value={p.confidence} confirmed={p.user_status === "confirmed" || p.source === "user"} />
                    <p className="mt-1 text-xs text-ink-faint">{p.evidence_count} episode{p.evidence_count === 1 ? "" : "s"}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {data.stickies.length > 0 && (
          <section className="mt-10">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-ink-soft">Explanations that clicked</h2>
            <div className="space-y-4">
              {data.stickies.map((s) => (
                <figure key={s.id} className="rounded-xl border border-line bg-panel p-4">
                  <figcaption className="mb-2 flex items-center justify-between text-xs text-ink-faint">
                    <span className="font-semibold text-ink">{s.concept}</span>
                    <Link href={`/s/${s.session_id}`} className="hover:text-accent">
                      open chat →
                    </Link>
                  </figcaption>
                  <blockquote className="border-l-2 border-accent pl-3">
                    <Markdown>{s.excerpt}</Markdown>
                  </blockquote>
                  {s.why && <p className="mt-2 text-sm text-ink-soft">{s.why}</p>}
                </figure>
              ))}
            </div>
          </section>
        )}

        {data.tutor_sees && (
          <details className="mt-10 rounded-xl border border-line bg-panel px-4 py-3 text-sm">
            <summary className="cursor-pointer text-ink-soft">What the tutor is told about you in this folder</summary>
            <pre className="mt-3 whitespace-pre-wrap font-mono text-xs leading-relaxed text-ink-soft">{data.tutor_sees}</pre>
          </details>
        )}
      </div>
    </div>
  );
}
