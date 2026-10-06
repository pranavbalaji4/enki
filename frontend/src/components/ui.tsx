"use client";

import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Mix } from "@/lib/api";

/** Markdown; links to app routes (/chats/1, /topics/2) navigate in place. */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose-enki">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) =>
            href?.startsWith("/") ? (
              <Link href={href}>{children}</Link>
            ) : (
              <a href={href} target="_blank" rel="noreferrer">
                {children}
              </a>
            ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

export const STRATEGY_LABEL: Record<string, string> = {
  analogy: "Analogy",
  concrete_example: "Example",
  worked_example: "Worked example",
  visual_diagram: "Diagram",
  formal_definition: "Formal definition",
  code: "Code",
  socratic_question: "Question back",
  first_principles: "First principles",
  contrast_counterexample: "Contrast",
  story: "Story",
  step_by_step: "Step by step",
  summary_recap: "Recap",
  example_first: "Example first",
  definition_first: "Definition first",
  question_first: "Question first",
};

export const VERDICT_LABEL: Record<string, string> = {
  applies_correctly: "You applied it",
  builds_on: "You built on it",
  paraphrase_correct: "You restated it",
  narrowing: "You narrowed in on a gap",
  ambiguous_ack: "Just an acknowledgement",
  topic_shift: "You moved on",
  re_ask: "You asked again",
  confusion: "You were lost",
  misconception: "You restated it wrongly",
  no_signal: "The chat ended here",
};

export function label(key: string | null | undefined, map: Record<string, string>) {
  if (!key) return "";
  return map[key] ?? key.replace(/_/g, " ");
}

/** The understanding scale, in display order. Index into level_probs: 0 not understood, 1 iffy, 2 understood. */
export const LEVELS = [
  { key: "understood", name: "Understood", probIndex: 2, bar: "bg-good", text: "text-good", soft: "bg-good-soft" },
  { key: "iffy", name: "Iffy", probIndex: 1, bar: "bg-mid", text: "text-mid", soft: "bg-mid-soft" },
  { key: "not_understood", name: "Not understood", probIndex: 0, bar: "bg-bad", text: "text-bad", soft: "bg-bad-soft" },
] as const;

export function topLevel(probs: number[]) {
  return LEVELS.reduce((best, l) => ((probs[l.probIndex] ?? 0) > (probs[best.probIndex] ?? 0) ? l : best), LEVELS[0]);
}

export function mixTotal(mix: Mix) {
  return mix.understood + mix.iffy + mix.not_understood;
}

/**
 * The landing bar: how much landed, as understood / iffy / not understood. Takes either counts (a mix) or one
 * reply's probabilities. Used at every scale, from all your chats down to a single reply.
 */
export function LandingBar({
  mix,
  probs,
  className = "h-2",
  title,
}: {
  mix?: Mix;
  probs?: number[];
  className?: string;
  title?: string;
}) {
  const parts = LEVELS.map((l) => ({ ...l, v: probs ? (probs[l.probIndex] ?? 0) : mix ? mix[l.key] : 0 }));
  const total = parts.reduce((s, p) => s + p.v, 0);
  const tip =
    title ??
    parts.map((p) => `${p.name}: ${probs ? `${Math.round(p.v * 100)}%` : p.v}`).join(", ");
  return (
    <span role="img" aria-label={tip} title={tip} className={`flex overflow-hidden rounded-full bg-sunken ${className}`}>
      {total > 0 &&
        parts.map((p) => (p.v > 0 ? <span key={p.key} className={p.bar} style={{ width: `${(p.v / total) * 100}%` }} /> : null))}
    </span>
  );
}

export function Chip({
  children,
  t = "none",
  title,
}: {
  children: React.ReactNode;
  t?: "good" | "mid" | "bad" | "none" | "accent";
  title?: string;
}) {
  const cls = {
    good: "bg-good-soft text-good",
    mid: "bg-mid-soft text-mid",
    bad: "bg-bad-soft text-bad",
    none: "bg-sunken text-ink-soft",
    accent: "bg-accent-soft text-accent",
  }[t];
  return (
    <span title={title} className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-xs font-medium ${cls}`}>
      {children}
    </span>
  );
}

/** Share of the evidence that supports a pattern (the Beta posterior mean). */
export function ConfidenceBar({ value, confirmed }: { value: number; confirmed?: boolean }) {
  const pct = Math.round(value * 100);
  const color = confirmed ? "bg-accent" : value >= 0.65 ? "bg-good" : value <= 0.35 ? "bg-bad" : "bg-mid";
  return (
    <span className="flex items-center gap-2" title={`${pct}% of the evidence supports this`}>
      <span className="h-1 w-16 overflow-hidden rounded-full bg-sunken">
        <span className={`block h-full ${color}`} style={{ width: `${pct}%` }} />
      </span>
      <span className="tabular w-8 text-right text-xs text-ink-soft">{pct}%</span>
    </span>
  );
}

export function Button({
  children,
  variant = "ghost",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" }) {
  const v = {
    primary: "bg-accent text-paper hover:brightness-110",
    ghost: "border border-line text-ink hover:bg-panel",
    danger: "border border-line text-bad hover:bg-bad-soft",
  }[variant];
  return (
    <button
      {...props}
      className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${v} ${props.className ?? ""}`}
    >
      {children}
    </button>
  );
}

/** A page's scroll container and measure. */
export function Page({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="h-full overflow-y-auto">
      <div className={`mx-auto px-5 py-8 md:px-10 md:py-12 ${wide ? "max-w-5xl" : "max-w-3xl"}`}>{children}</div>
    </div>
  );
}

export function SectionTitle({ children, aside }: { children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-4 border-b border-line pb-2">
      <h2 className="font-serif text-lg font-semibold">{children}</h2>
      {aside && <span className="text-sm text-ink-faint">{aside}</span>}
    </div>
  );
}

export function ErrorNote({ children }: { children: React.ReactNode }) {
  return <p className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{children}</p>;
}

export function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function pct(n: number | null | undefined) {
  return n == null ? "–" : `${Math.round(n * 100)}%`;
}
