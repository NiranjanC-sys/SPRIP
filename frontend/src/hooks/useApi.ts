import { useState, useEffect, useCallback, useRef } from "react";

type Status = "idle" | "loading" | "success" | "error";

interface UseApiResult<T> {
  data: T | null;
  status: Status;
  error: string | null;
  refetch: () => void;
}

const cache = new Map<string, { data: unknown; ts: number }>();
const CACHE_TTL = 5 * 60 * 1000;

function getCached<T>(key: string): T | null {
  const entry = cache.get(key);
  if (!entry) return null;
  if (Date.now() - entry.ts > CACHE_TTL) {
    cache.delete(key);
    return null;
  }
  return entry.data as T;
}

function setCache(key: string, data: unknown) {
  cache.set(key, { data, ts: Date.now() });
}

export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
  cacheKey?: string
): UseApiResult<T> {
  const resolved = cacheKey ?? depsToKey(deps);
  const cached = getCached<T>(resolved);

  const [data, setData] = useState<T | null>(cached);
  const [status, setStatus] = useState<Status>(cached ? "success" : "idle");
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const execute = useCallback(() => {
    const hit = getCached<T>(resolved);
    if (hit) {
      setData(hit);
      setStatus("success");
      setError(null);
      return;
    }
    setStatus("loading");
    setError(null);
    fetcher()
      .then((result) => {
        if (!mountedRef.current) return;
        setCache(resolved, result);
        setData(result);
        setStatus("success");
      })
      .catch((err: unknown) => {
        if (!mountedRef.current) return;
        setError(err instanceof Error ? err.message : "Unknown error");
        setStatus("error");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    execute();
  }, [execute]);

  const refetch = useCallback(() => {
    cache.delete(resolved);
    execute();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolved, execute]);

  return { data, status, error, refetch };
}

function depsToKey(deps: unknown[]): string {
  try {
    return JSON.stringify(deps);
  } catch {
    return String(deps);
  }
}

export function clearApiCache() {
  cache.clear();
}
