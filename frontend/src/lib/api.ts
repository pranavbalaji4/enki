import type { components } from "./api-types";

type S = components["schemas"];
export type NodeOut = S["NodeOut"];
export type SessionOut = S["SessionOut"];
export type MessageOut = S["MessageOut"];
export type AnnotationOut = S["AnnotationOut"];
export type EpisodeOut = S["EpisodeOut"];
export type ProfileOut = S["ProfileOut"];
export type ProfileEditOut = S["ProfileEditOut"];
export type PatternOut = S["PatternOut"];
export type InsightOut = S["InsightOut"];

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

export const api = {
  tree: () => req<NodeOut[]>("/api/tree"),
  createNode: (body: S["NodeCreate"]) => req<NodeOut>("/api/nodes", { method: "POST", body: JSON.stringify(body) }),
  renameNode: (id: number, title: string) =>
    req<NodeOut>(`/api/nodes/${id}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  deleteNode: (id: number) => req<{ ok: boolean }>(`/api/nodes/${id}`, { method: "DELETE" }),
  session: (id: number) => req<SessionOut>(`/api/sessions/${id}`),
  wrapUp: (id: number) => req<{ ok: boolean }>(`/api/sessions/${id}/wrap-up`, { method: "POST" }),
  profile: (nodeId: number) => req<ProfileOut>(`/api/profile/${nodeId}`),
  editProfile: (nodeId: number, markdown: string) =>
    req<ProfileEditOut>(`/api/profile/${nodeId}`, { method: "PUT", body: JSON.stringify({ markdown }) }),
  insights: (status: string | null = "new") =>
    req<InsightOut[]>(`/api/insights${status ? `?status=${status}` : "?status="}`),
  insightFeedback: (id: number, action: "confirm" | "reject" | "dismiss", note = "") =>
    req<{ ok: boolean }>(`/api/insights/${id}/feedback`, { method: "POST", body: JSON.stringify({ action, note }) }),
};

export type StreamEvent =
  | { type: "user_message"; id: number }
  | { type: "delta"; text: string }
  | { type: "done"; id: number }
  | { type: "error"; message: string };

/** POST a chat message and read the tutor's reply as server-sent events. */
export async function streamMessage(sessionId: number, content: string, onEvent: (e: StreamEvent) => void) {
  const res = await fetch(`${API_URL}/api/sessions/${sessionId}/messages`, {
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
