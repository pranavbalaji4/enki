"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useAppState } from "@/components/AppState";
import { Button } from "@/components/ui";
import { api } from "@/lib/api";

export default function Home() {
  const { nodes, newInsights, refresh } = useAppState();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const recent = [...nodes].filter((n) => n.kind === "session").sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 5);

  async function quickStart() {
    setBusy(true);
    const cs = await api.createNode({ kind: "folder", title: "CS" });
    const topic = await api.createNode({ kind: "folder", title: "Data Structures", parent_id: cs.id });
    const chat = await api.createNode({ kind: "session", title: "Lec 1: Heaps", parent_id: topic.id });
    await refresh();
    router.push(`/s/${chat.id}`);
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-2xl px-6 py-16">
        <h1 className="font-serif text-4xl font-semibold leading-tight">Learn anything. Find out how you learn.</h1>
        <p className="mt-4 text-lg leading-relaxed text-ink-soft">
          Enki is a tutor that watches which explanations actually land for you — an analogy, a worked example, a diagram — by
          reading how you reply. Over time it builds a picture of how <em>you</em> learn, shows it to you, and teaches you that way.
        </p>

        <ol className="mt-8 space-y-3 text-[15px]">
          <Step n={1}>Organize by subject → topic → chat (e.g. CS / Data Structures / Lec 7: Heaps).</Step>
          <Step n={2}>Ask questions and reply honestly — “huh?”, “so it’s like…?”, “why?”. The learning lens shows how each reply landed.</Step>
          <Step n={3}>Press <strong>Wrap up</strong> at the end: Enki finds where things clicked, saves those explanations, and updates your profile.</Step>
          <Step n={4}>Confirm or reject what it noticed in <Link href="/insights" className="text-accent underline">Insights</Link>, or edit your profile directly.</Step>
        </ol>

        <div className="mt-10 flex flex-wrap gap-3">
          {nodes.length === 0 ? (
            <Button variant="primary" onClick={quickStart} disabled={busy}>
              Start with CS / Data Structures
            </Button>
          ) : (
            newInsights > 0 && (
              <Button variant="primary" onClick={() => router.push("/insights")}>
                {newInsights} new insight{newInsights === 1 ? "" : "s"} →
              </Button>
            )
          )}
          <Button onClick={() => router.push("/n/0")}>Your global profile</Button>
        </div>

        {recent.length > 0 && (
          <section className="mt-12">
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-ink-faint">Recent chats</h2>
            <div className="space-y-1">
              {recent.map((n) => (
                <Link key={n.id} href={`/s/${n.id}`} className="block rounded-lg px-3 py-2 hover:bg-sunken">
                  {n.status === "reviewed" ? "✦ " : "· "}
                  {n.title}
                </Link>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

function Step({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent">{n}</span>
      <span className="text-ink-soft">{children}</span>
    </li>
  );
}
