"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, type NodeOut } from "@/lib/api";

type AppState = {
  nodes: NodeOut[];
  newInsights: number;
  backendError: string | null;
  refresh: () => Promise<void>;
};

async function fetchState() {
  try {
    const [tree, insights] = await Promise.all([api.tree(), api.insights("new")]);
    return { ok: true as const, tree, newInsights: insights.length };
  } catch {
    return { ok: false as const };
  }
}

const Ctx = createContext<AppState | null>(null);

export function AppStateProvider({ children }: { children: React.ReactNode }) {
  const [nodes, setNodes] = useState<NodeOut[]>([]);
  const [newInsights, setNewInsights] = useState(0);
  const [backendError, setBackendError] = useState<string | null>(null);

  const apply = useCallback((r: Awaited<ReturnType<typeof fetchState>>) => {
    if (r.ok) {
      setNodes(r.tree);
      setNewInsights(r.newInsights);
      setBackendError(null);
    } else setBackendError("Can't reach the Enki backend. Is it running on port 8000?");
  }, []);

  const refresh = useCallback(async () => apply(await fetchState()), [apply]);

  useEffect(() => {
    fetchState().then(apply);
  }, [apply]);

  return <Ctx.Provider value={{ nodes, newInsights, backendError, refresh }}>{children}</Ctx.Provider>;
}

export function useAppState() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAppState outside provider");
  return v;
}

export function pathOf(nodes: NodeOut[], id: number | null | undefined): NodeOut[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const out: NodeOut[] = [];
  let cur = id != null ? byId.get(id) : undefined;
  while (cur) {
    out.unshift(cur);
    cur = cur.parent_id != null ? byId.get(cur.parent_id) : undefined;
  }
  return out;
}
