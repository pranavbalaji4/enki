"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAppState } from "@/components/AppState";
import { PatternList, StickyList } from "@/components/Evidence";
import {
  Button,
  ErrorNote,
  LEVELS,
  LandingBar,
  Markdown,
  Page,
  SectionTitle,
  formatDate,
  mixTotal,
} from "@/components/ui";
import { api, type InsightOut, type Mix, type OverviewOut, type TopicOut } from "@/lib/api";

export default function InsightsPage() {
  const { dataVersion } = useAppState();
  const [data, setData] = useState<OverviewOut | null>(null);
  const [cards, setCards] = useState<InsightOut[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.overview(), api.insights("pattern")]).then(
      ([o, c]) => {
        setData(o);
        setCards(c);
        setError(null);
      },
      (e: Error) => setError(e.message),
    );
  }, [dataVersion]);

  if (error) return <Page><ErrorNote>{error}</ErrorNote></Page>;
  if (!data) return null;
  if (data.stats.chats === 0) return <Welcome />;
  if (data.stats.analyzed_chats === 0) return <NotAnalyzed pending={data.stats.pending_chats} />;

  const judged = mixTotal(data.mix);
  return (
    <Page wide>
      <header className="max-w-3xl">
        <p className="text-sm text-ink-faint">
          From {data.stats.analyzed_chats} analyzed conversation{data.stats.analyzed_chats === 1 ? "" : "s"} across{" "}
          {data.stats.topics} topic{data.stats.topics === 1 ? "" : "s"}
          {data.snapshot && <>, updated {formatDate(data.snapshot.created_at)}</>}
        </p>
        {data.snapshot ? (
          <>
            <h1 className="settle mt-3 font-serif text-3xl font-medium leading-snug tracking-tight md:text-[2.5rem] md:leading-[1.2]">
              {data.snapshot.headline}
            </h1>
            <div className="mt-6 max-w-[68ch] text-ink-soft">
              <Markdown>{data.snapshot.summary_md}</Markdown>
            </div>
          </>
        ) : (
          <h1 className="mt-3 font-serif text-3xl font-medium">Your profile is written at the end of each analysis.</h1>
        )}
        {data.stats.pending_chats > 0 && (
          <p className="mt-4 text-sm text-ink-soft">
            {data.stats.pending_chats} more chat{data.stats.pending_chats === 1 ? " is" : "s are"} waiting.{" "}
            <Link href="/import" className="text-accent underline underline-offset-2">
              Analyze them
            </Link>
          </p>
        )}
      </header>

      <section className="mt-14">
        <SectionTitle aside={`${judged} replies judged`}>How Claude’s explanations landed</SectionTitle>
        <LandingBar mix={data.mix} className="h-3" />
        <Legend mix={data.mix} />
        <p className="mt-3 max-w-[68ch] text-sm text-ink-faint">
          Each reply is judged from the message you sent next: building on it or restating it counts as understood, a
          bare “ok” or a follow-up on one gap as iffy, asking again or being lost as not understood. The last reply in a
          chat has nothing after it, so it isn’t counted.
        </p>
      </section>

      {cards.length > 0 && <Cards cards={cards} onChange={(id) => setCards((c) => c.filter((x) => x.id !== id))} />}

      <section className="mt-14">
        <SectionTitle aside="by how well explanations landed">Topics</SectionTitle>
        <TopicMap topics={data.topics} />
      </section>

      <div className="mt-14 grid gap-14 lg:grid-cols-2">
        <section>
          <SectionTitle>Across your topics</SectionTitle>
          {data.global_patterns.length ? (
            <PatternList patterns={data.global_patterns} showTopics />
          ) : (
            <p className="text-sm text-ink-faint">
              A pattern shows up here once it holds in two or more topics. Analyze more chats to find them.
            </p>
          )}
        </section>
        <section>
          <SectionTitle>Strongest within a topic</SectionTitle>
          {data.top_patterns.length ? (
            <PatternList patterns={data.top_patterns} showScope />
          ) : (
            <p className="text-sm text-ink-faint">No patterns yet.</p>
          )}
        </section>
      </div>

      {data.stickies.length > 0 && (
        <section className="mt-14">
          <SectionTitle>Explanations that clicked</SectionTitle>
          <StickyList stickies={data.stickies} />
        </section>
      )}
    </Page>
  );
}

function Legend({ mix }: { mix: Mix }) {
  const total = mixTotal(mix) || 1;
  return (
    <div className="mt-3 flex flex-wrap gap-x-8 gap-y-2">
      {LEVELS.map((l) => (
        <div key={l.key} className="flex items-baseline gap-2">
          <span className={`h-2 w-2 translate-y-[-1px] rounded-full ${l.bar}`} aria-hidden />
          <span className="text-sm text-ink-soft">{l.name}</span>
          <span className={`tabular font-serif text-xl ${l.text}`}>{Math.round((mix[l.key] / total) * 100)}%</span>
          <span className="tabular text-xs text-ink-faint">{mix[l.key]}</span>
        </div>
      ))}
    </div>
  );
}

function TopicMap({ topics }: { topics: TopicOut[] }) {
  const domains = topics.filter((t) => t.parent_id == null && t.chat_count > 0).sort((a, b) => b.chat_count - a.chat_count);
  const max = Math.max(1, ...topics.map((t) => t.chat_count));
  if (!domains.length) return <p className="text-sm text-ink-faint">No topics yet.</p>;
  return (
    <div className="grid gap-x-12 gap-y-10 md:grid-cols-2">
      {domains.map((d) => (
        <div key={d.id}>
          <div className="flex items-baseline justify-between gap-3">
            <Link href={`/topics/${d.id}`} className="font-serif text-lg font-semibold hover:text-accent">
              {d.title}
            </Link>
            <span className="tabular text-xs text-ink-faint">
              {d.chat_count} chat{d.chat_count === 1 ? "" : "s"}
            </span>
          </div>
          <LandingBar mix={d.mix} className="mt-2 h-1.5" />
          <ul className="mt-3 space-y-3">
            {topics
              .filter((t) => t.parent_id === d.id && t.chat_count > 0)
              .sort((a, b) => b.chat_count - a.chat_count)
              .map((t) => (
                <li key={t.id}>
                  <Link href={`/topics/${t.id}`} className="group block">
                    <span className="flex items-center gap-3">
                      <span className="min-w-0 flex-1 truncate text-sm group-hover:text-accent">{t.title}</span>
                      {/* Bar length is how much you've asked about it; its colors are how well it landed. */}
                      <span className="w-28 shrink-0">
                        <span className="block" style={{ width: `${Math.max(15, (t.chat_count / max) * 100)}%` }}>
                          <LandingBar
                            mix={t.mix}
                            className="h-1.5"
                            title={`${t.chat_count} chats, ${t.judged_turns} judged replies`}
                          />
                        </span>
                      </span>
                      <span className="tabular w-6 shrink-0 text-right text-xs text-ink-faint">{t.chat_count}</span>
                    </span>
                    {t.line && <span className="mt-0.5 block text-sm text-ink-faint">{t.line}</span>}
                  </Link>
                </li>
              ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function Cards({ cards, onChange }: { cards: InsightOut[]; onChange: (id: number) => void }) {
  async function act(id: number, action: "confirm" | "reject" | "dismiss") {
    await api.insightFeedback(id, action);
    onChange(id);
  }
  return (
    <section className="mt-14">
      <SectionTitle aside="your answer weighs more than any chat">Does this sound like you?</SectionTitle>
      <ul className="divide-y divide-line">
        {cards.map((c) => (
          <li key={c.id} className="py-4">
            <p className="font-serif text-lg">{c.title}</p>
            <p className="mt-0.5 text-xs text-ink-faint">{c.scope}</p>
            <div className="mt-2 max-w-[68ch] text-sm text-ink-soft [&_.prose-enki]:text-[0.92rem]">
              <Markdown>{c.body}</Markdown>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant="primary" onClick={() => act(c.id, "confirm")}>
                Yes, that’s me
              </Button>
              <Button onClick={() => act(c.id, "reject")}>No, it isn’t</Button>
              <Button onClick={() => act(c.id, "dismiss")} className="border-transparent text-ink-faint">
                Not sure
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Welcome() {
  return (
    <Page>
      <h1 className="settle font-serif text-4xl font-medium leading-tight tracking-tight">
        See how you learn, read from your own conversations with Claude.
      </h1>
      <p className="mt-5 max-w-[60ch] text-lg leading-relaxed text-ink-soft">
        Enki reads your claude.ai history, finds the chats where you were learning something, and checks which
        explanations actually landed for you, judged from how you replied. It sorts them into topics and writes up what
        works for you.
      </p>
      <div className="mt-8">
        <Link
          href="/import"
          className="inline-flex rounded-lg bg-accent px-4 py-2 text-sm font-medium text-paper hover:brightness-110"
        >
          Import your chats
        </Link>
      </div>
    </Page>
  );
}

function NotAnalyzed({ pending }: { pending: number }) {
  return (
    <Page>
      <h1 className="font-serif text-3xl font-medium">
        {pending} chat{pending === 1 ? " is" : "s are"} imported and waiting to be analyzed.
      </h1>
      <p className="mt-4 text-ink-soft">Your insights appear here once the first analysis finishes.</p>
      <div className="mt-6">
        <Link
          href="/import"
          className="inline-flex rounded-lg bg-accent px-4 py-2 text-sm font-medium text-paper hover:brightness-110"
        >
          Review the estimate and analyze
        </Link>
      </div>
    </Page>
  );
}
