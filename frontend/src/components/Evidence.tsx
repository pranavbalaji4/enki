"use client";

import Link from "next/link";
import type { PatternOut, StickyOut } from "@/lib/api";
import { ConfidenceBar, STRATEGY_LABEL, label } from "./ui";

/** Patterns as a ruled list: the claim, where it comes from, and how strong the evidence is. */
export function PatternList({
  patterns,
  showScope = false,
  showTopics = false,
}: {
  patterns: PatternOut[];
  showScope?: boolean;
  showTopics?: boolean;
}) {
  return (
    <ul className="divide-y divide-line">
      {patterns.map((p) => {
        const confirmed = p.user_status === "confirmed" || p.user_status === "edited" || p.source === "user";
        const where = showTopics && p.topics.length ? `seen in ${p.topics.join(", ")}` : showScope ? `in ${p.scope}` : "";
        return (
          <li key={p.id} className="flex gap-4 py-3">
            <div className="min-w-0 flex-1">
              <p className="text-[15px] leading-snug">{p.claim}</p>
              <p className="mt-1 text-xs text-ink-faint">
                {label(p.strategy, STRATEGY_LABEL)}
                {where && `, ${where}`}
                {confirmed && ", confirmed by you"}
              </p>
            </div>
            <div className="shrink-0 text-right">
              <ConfidenceBar value={p.confidence} confirmed={confirmed} />
              <p className="tabular mt-1 text-xs text-ink-faint">
                {p.evidence_count} episode{p.evidence_count === 1 ? "" : "s"}
              </p>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** Explanations that clicked, quoted verbatim from Claude's reply. */
export function StickyList({ stickies }: { stickies: StickyOut[] }) {
  return (
    <div className="grid gap-x-10 gap-y-8 md:grid-cols-2">
      {stickies.map((s) => (
        <figure key={s.id}>
          <figcaption className="text-sm font-medium">{s.concept}</figcaption>
          <blockquote className="mt-2 border-l-2 border-good pl-4 font-serif text-[15px] leading-relaxed text-ink-soft">
            {s.excerpt.length > 420 ? `${s.excerpt.slice(0, 420).trimEnd()}…` : s.excerpt}
          </blockquote>
          {s.why && <p className="mt-2 pl-4 text-sm text-ink-faint">{s.why}</p>}
          <Link href={`/chats/${s.session_id}`} className="mt-1 inline-block pl-4 text-sm text-accent hover:underline">
            Open “{s.chat_title}”
          </Link>
        </figure>
      ))}
    </div>
  );
}
