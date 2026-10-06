import type { components } from "./api-types";

type S = components["schemas"];
export type NodeOut = S["NodeOut"];
export type OverviewOut = S["OverviewOut"];
export type TopicOut = S["TopicOut"];
export type TopicDetailOut = S["TopicDetailOut"];
export type ChatOut = S["ChatOut"];
export type ChatSummaryOut = S["ChatSummaryOut"];
export type AnnotationOut = S["AnnotationOut"];
export type EpisodeOut = S["EpisodeOut"];
export type PatternOut = S["PatternOut"];
export type StickyOut = S["StickyOut"];
export type InsightOut = S["InsightOut"];
export type ImportOut = S["ImportOut"];
export type Estimate = S["Estimate"];
export type RunOut = S["RunOut"];
export type AskMessageOut = S["AskMessageOut"];
export type Mix = S["Mix"];

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

export const api = {
  tree: () => req<NodeOut[]>("/api/tree"),
  renameNode: (id: number, title: string) => req<NodeOut>(`/api/nodes/${id}`, json("PATCH", { title })),
  overview: () => req<OverviewOut>("/api/overview"),
  topic: (id: number) => req<TopicDetailOut>(`/api/topics/${id}`),
  chat: (id: number) => req<ChatOut>(`/api/chats/${id}`),
  setLearning: (id: number, is_learning: boolean) => req<ChatSummaryOut>(`/api/chats/${id}`, json("PATCH", { is_learning })),
  uploadExport: (file: File) =>
    req<ImportOut>("/api/imports", { method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" } }),
  estimate: (limit?: number) => req<Estimate>(`/api/analysis/estimate${limit ? `?limit=${limit}` : ""}`),
  startAnalysis: (limit?: number) => req<RunOut>("/api/analysis", json("POST", { limit: limit ?? null })),
  latestRun: () => req<RunOut | null>("/api/analysis/latest"),
  insights: (kind?: string) => req<InsightOut[]>(`/api/insights?status=new${kind ? `&kind=${kind}` : ""}`),
  insightFeedback: (id: number, action: "confirm" | "reject" | "dismiss", note = "") =>
    req<{ ok: boolean }>(`/api/insights/${id}/feedback`, json("POST", { action, note })),
  askHistory: () => req<AskMessageOut[]>("/api/ask"),
  clearAsk: () => req<{ ok: boolean }>("/api/ask", { method: "DELETE" }),
};

export type AskEvent =
  | { type: "user_message"; id: number }
  | { type: "tool"; name: string; label: string }
  | { type: "delta"; text: string }
  | { type: "done"; id: number }
  | { type: "error"; message: string };

/** POST a question and read the answer as server-sent events. */
export async function streamAsk(content: string, onEvent: (e: AskEvent) => void) {
  const res = await fetch(`${API_URL}/api/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!res.ok || !res.body) {
    onEvent({ type: "error", message: `Request failed (${res.status})` });
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      if (chunk.startsWith("data: ")) onEvent(JSON.parse(chunk.slice(6)));
    }
  }
}
