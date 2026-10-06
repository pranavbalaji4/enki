"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useAppState } from "@/components/AppState";
import { PatternList, StickyList } from "@/components/Evidence";
import { ErrorNote, LEVELS, LandingBar, Page, SectionTitle, formatDate, mixTotal, pct } from "@/components/ui";
import { api, type TopicDetailOut } from "@/lib/api";

export default function TopicPage() {
  const { id } = useParams<{ id: string }>();
  const { dataVersion } = useAppState();
  const [data, setData] = useState<TopicDetailOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.topic(Number(id)).then(
      (d) => {
        setData(d);
        setError(null);
      },
      (e: Error) => setError(e.message),
    );
  }, [id, dataVersion]);

  if (error) return <Page><ErrorNote>{error}</ErrorNote></Page>;
  if (!data) return null;
  const t = data.topic;
  const judged = mixTotal(t.mix);

  return (
    <Page wide>
      <nav className="text-sm text-ink-faint" aria-label="Breadcrumb">
        <Link href="/" className="hover:text-accent">
          Insights
        </Link>
        {data.breadcrumbs.map((c) => (
          <span key={c.id}>
            <span className="mx-2">/</span>
            <Link href={`/topics/${c.id}`} className="hover:text-accent">
              {c.title}
            </Link>
          </span>
        ))}
      </nav>
      <h1 className="mt-3 font-serif text-4xl font-medium tracking-tight">{t.title}</h1>
      {t.line && <p className="mt-3 max-w-[64ch] font-serif text-lg text-ink-soft">{t.line}</p>}

      <div className="mt-8 grid gap-6 sm:grid-cols-[1fr_auto] sm:items-end">
        <div>
          <LandingBar mix={t.mix} className="h-3" />
          <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-sm">
            {LEVELS.map((l) => (
              <span key={l.key} className="text-ink-soft">
                <span className={`tabular ${l.text}`}>{judged ? Math.round((t.mix[l.key] / judged) * 100) : 0}%</span>{" "}
                {l.name.toLowerCase()}
              </span>
            ))}
          </div>
        </div>
        <dl className="flex gap-8 text-sm">
          <Stat label="Chats" value={String(t.chat_count)} />
          <Stat label="Replies judged" value={String(judged)} />
          <Stat label="Avg. understanding" value={pct(t.avg_understanding)} />
        </dl>
      </div>

      {data.summary && (
        <section className="mt-12 max-w-[68ch]">
          <SectionTitle>What you covered</SectionTitle>
          <p className="whitespace-pre-line font-serif leading-relaxed text-ink-soft">{data.summary}</p>
        </section>
      )}

      {data.children.length > 0 && (
        <section className="mt-12">
          <SectionTitle>Topics</SectionTitle>
          <ul className="grid gap-x-10 gap-y-4 md:grid-cols-2">
            {data.children.map((c) => (
              <li key={c.id}>
                <Link href={`/topics/${c.id}`} className="group block">
                  <span className="flex items-baseline justify-between gap-3">
                    <span className="group-hover:text-accent">{c.title}</span>
                    <span className="tabular text-xs text-ink-faint">{c.chat_count} chats</span>
                  </span>
                  <LandingBar mix={c.mix} className="mt-1.5 h-1.5" />
                  {c.line && <span className="mt-1 block text-sm text-ink-faint">{c.line}</span>}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="mt-12">
        <SectionTitle>What works for you here</SectionTitle>
        {data.patterns.length ? (
          <PatternList patterns={data.patterns} showScope={data.children.length > 0} />
        ) : (
          <p className="text-sm text-ink-faint">No patterns yet. They need a few analyzed chats in this topic.</p>
        )}
      </section>

      {data.stickies.length > 0 && (
        <section className="mt-12">
          <SectionTitle>Explanations that clicked</SectionTitle>
          <StickyList stickies={data.stickies} />
        </section>
      )}

      <section className="mt-12">
        <SectionTitle aside={`${data.chats.length}`}>Chats</SectionTitle>
        <ul className="divide-y divide-line">
          {data.chats.map((c) => (
            <li key={c.id}>
              <Link href={`/chats/${c.id}`} className="group flex items-center gap-4 py-2.5">
                <span className="min-w-0 flex-1">
                  <span className="block truncate group-hover:text-accent">{c.title}</span>
                  <span className="text-xs text-ink-faint">
                    {formatDate(c.started_at)}
                    {c.status !== "analyzed" && `, ${c.status === "pending" ? "not analyzed yet" : c.status}`}
                  </span>
                </span>
                <span className="w-24 shrink-0">
                  {c.judged_turns > 0 && <LandingBar mix={c.mix} className="h-1.5" />}
                </span>
                <span className="tabular w-16 shrink-0 text-right text-xs text-ink-faint">
                  {c.judged_turns} repl{c.judged_turns === 1 ? "y" : "ies"}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </Page>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-ink-faint">{label}</dt>
      <dd className="tabular font-serif text-2xl">{value}</dd>
    </div>
  );
}
