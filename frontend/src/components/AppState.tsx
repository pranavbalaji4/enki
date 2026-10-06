"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, type NodeOut, type RunOut } from "@/lib/api";

type AppState = {
  nodes: NodeOut[];
  run: RunOut | null;
  /** Bumps when an analysis run finishes, so pages showing analyzed data can reload. */
  dataVersion: number;
  backendError: string | null;
  refresh: () => Promise<void>;
  watchRun: (run: RunOut) => void;
};

async function fetchState() {
  try {
    const [tree, latest] = await Promise.all([api.tree(), api.latestRun()]);
    return { ok: true as const, tree, latest };
  } catch {
    return { ok: false as const };
  }
}

const Ctx = createContext<AppState | null>(null);

const isActive = (r: RunOut | null) => !!r && (r.status === "queued" || r.status === "running");

export function AppStateProvider({ children }: { children: React.ReactNode }) {
  const [nodes, setNodes] = useState<NodeOut[]>([]);
  const [run, setRun] = useState<RunOut | null>(null);
  const [dataVersion, setDataVersion] = useState(0);
  const [backendError, setBackendError] = useState<string | null>(null);

  const apply = useCallback((r: Awaited<ReturnType<typeof fetchState>>) => {
    if (r.ok) {
      setNodes(r.tree);
      setRun(r.latest);
      setBackendError(null);
    } else setBackendError("Can't reach the Enki backend. Start it on port 8000, then reload.");
  }, []);

  const refresh = useCallback(async () => apply(await fetchState()), [apply]);

  useEffect(() => {
    fetchState().then(apply);
  }, [apply]);

  // While a run is going, poll its progress; when it ends, reload everything that depends on it.
  const active = isActive(run);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(async () => {
      const next = await api.latestRun().catch(() => null);
      if (!next) return;
      setRun(next);
      if (!isActive(next)) {
        setNodes(await api.tree().catch(() => []));
        setDataVersion((v) => v + 1);
      } else if (next.stage !== run?.stage) {
        setNodes(await api.tree().catch(() => []));
      }
    }, 1500);
    return () => clearInterval(t);
  }, [active, run?.stage]);

  const watchRun = useCallback((r: RunOut) => setRun(r), []);

  return (
    <Ctx.Provider value={{ nodes, run, dataVersion, backendError, refresh, watchRun }}>{children}</Ctx.Provider>
  );
}

export function useAppState() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAppState outside provider");
  return v;
}

export function runIsActive(run: RunOut | null) {
  return isActive(run);
}
