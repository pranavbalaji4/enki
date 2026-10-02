"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose-enki">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
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
  socratic_question: "Question",
  first_principles: "First principles",
  contrast_counterexample: "Contrast",
  story: "Story",
  step_by_step: "Step by step",
  summary_recap: "Recap",
  example_first: "Example first",
  definition_first: "Definition first",
};

export const VERDICT_LABEL: Record<string, string> = {
  applies_correctly: "You applied it",
  builds_on: "You built on it",
  paraphrase_correct: "You restated it",
  narrowing: "Partly — you narrowed in",
  ambiguous_ack: "Unclear",
  topic_shift: "You moved on",
  re_ask: "You asked again",
  confusion: "Didn't land",
  misconception: "Misread",
};

export function label(key: string | null | undefined, map: Record<string, string>) {
  if (!key) return "";
  return map[key] ?? key.replace(/_/g, " ");
}

export function tone(understanding: number | null | undefined): "good" | "mid" | "bad" | "none" {
  if (understanding == null) return "none";
  if (understanding >= 0.7) return "good";
  if (understanding >= 0.45) return "mid";
  return "bad";
}

const TONE_CLASS = {
  good: "bg-good-soft text-good",
  mid: "bg-mid-soft text-mid",
  bad: "bg-bad-soft text-bad",
  none: "bg-sunken text-ink-soft",
  accent: "bg-accent-soft text-accent",
};

export function Chip({ children, t = "none", title }: { children: React.ReactNode; t?: keyof typeof TONE_CLASS; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11.5px] font-medium ${TONE_CLASS[t]}`}>
      {children}
    </span>
  );
}

export function ConfidenceBar({ value, confirmed }: { value: number; confirmed?: boolean }) {
  const pct = Math.round(value * 100);
  const color = confirmed ? "bg-accent" : value >= 0.65 ? "bg-good" : value <= 0.35 ? "bg-bad" : "bg-mid";
  return (
    <div className="flex items-center gap-2" title={`${pct}% of the evidence supports this`}>
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-sunken">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-9 text-right text-xs tabular-nums text-ink-soft">{pct}%</span>
    </div>
  );
}

export function Button({
  children,
  variant = "ghost",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" }) {
  const v = {
    primary: "bg-accent text-panel hover:opacity-90",
    ghost: "border border-line text-ink hover:bg-sunken",
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
