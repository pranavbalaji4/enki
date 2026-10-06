"use client";

import { useEffect, useRef, useState } from "react";
import { Button, ErrorNote, Markdown } from "@/components/ui";
import { api, streamAsk, type AskMessageOut } from "@/lib/api";

const STARTERS = [
  "What kind of explanation works best for me?",
  "Where do I get stuck most often?",
  "How do I learn differently in finance and in computer science?",
  "How should I prompt Claude when I'm learning something new?",
];

type Pending = { question: string; answer: string; tools: string[] } | null;

export default function AskPage() {
  const [history, setHistory] = useState<AskMessageOut[]>([]);
  const [pending, setPending] = useState<Pending>(null);
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.askHistory().then(setHistory, (e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [history.length, pending?.answer, pending?.tools.length]);

  async function ask(text: string) {
    const q = text.trim();
    if (!q || pending) return;
    setInput("");
    setError(null);
    setPending({ question: q, answer: "", tools: [] });
    let failed = false;
    await streamAsk(q, (ev) => {
      if (ev.type === "delta") setPending((p) => (p ? { ...p, answer: p.answer + ev.text } : p));
      if (ev.type === "tool") setPending((p) => (p ? { ...p, tools: [...p.tools, ev.label] } : p));
      if (ev.type === "error") {
        failed = true;
        setError(ev.message);
        setInput(q);
      }
    }).catch((e: Error) => {
      failed = true;
      setError(e.message);
      setInput(q);
    });
    if (!failed) setHistory(await api.askHistory().catch(() => history));
    setPending(null);
  }

  async function clear() {
    await api.clearAsk();
    setHistory([]);
  }

  const empty = !history.length && !pending;

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-5 py-8 md:px-10 md:py-12">
          <div className="flex items-baseline justify-between gap-4">
            <h1 className="font-serif text-3xl font-medium tracking-tight">Ask about how you learn</h1>
            {history.length > 0 && (
              <button onClick={clear} className="text-sm text-ink-faint hover:text-ink">
                Clear conversation
              </button>
            )}
          </div>
          {empty && (
            <>
              <p className="mt-3 max-w-[60ch] text-ink-soft">
                Answers come from your analyzed chats: your topics, how each reply landed, and the patterns found in them.
                Claude looks things up before it answers and links to the conversations it used.
              </p>
              <ul className="mt-8 divide-y divide-line border-y border-line">
                {STARTERS.map((s) => (
                  <li key={s}>
                    <button onClick={() => ask(s)} className="w-full py-3 text-left font-serif text-lg hover:text-accent">
                      {s}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}

          <div className="mt-8 space-y-8">
            {history.map((m) => (m.role === "user" ? <Question key={m.id} text={m.content} /> : <Answer key={m.id} text={m.content} />))}
            {pending && (
              <>
                <Question text={pending.question} />
                <div>
                  {pending.tools.length > 0 && (
                    <ul className="mb-3 space-y-1 text-sm text-ink-faint" aria-live="polite">
                      {pending.tools.map((t, i) => (
                        <li key={i}>{t}</li>
                      ))}
                    </ul>
                  )}
                  {pending.answer ? (
                    <Answer text={pending.answer} />
                  ) : (
                    !pending.tools.length && <p className="text-sm text-ink-faint">Thinking</p>
                  )}
                </div>
              </>
            )}
          </div>
          <div ref={bottomRef} className="h-4" />
        </div>
      </div>

      <div className="border-t border-line bg-sunken px-5 py-4 md:px-10">
        <div className="mx-auto max-w-3xl">
          {error && (
            <div className="mb-2">
              <ErrorNote>{error}</ErrorNote>
            </div>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              ask(input);
            }}
            className="flex items-end gap-2 rounded-xl border border-line bg-panel p-2 focus-within:border-accent"
          >
            <textarea
              value={input}
              aria-label="Your question"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  ask(input);
                }
              }}
              rows={Math.min(6, Math.max(1, input.split("\n").length))}
              placeholder="Ask anything about how you learn"
              className="max-h-40 flex-1 resize-none bg-transparent px-2 py-1.5 text-[15px] outline-none placeholder:text-ink-faint"
            />
            <Button type="submit" variant="primary" disabled={!input.trim() || !!pending}>
              Ask
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}

function Question({ text }: { text: string }) {
  return <p className="whitespace-pre-wrap font-serif text-xl leading-snug">{text}</p>;
}

function Answer({ text }: { text: string }) {
  return (
    <div className="border-l-2 border-line pl-5">
      <Markdown>{text}</Markdown>
    </div>
  );
}
