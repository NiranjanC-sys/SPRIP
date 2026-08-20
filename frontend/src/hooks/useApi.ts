import { useState, useEffect, useCallback } from "react";

type Status = "idle" | "loading" | "success" | "error";

interface UseApiResult<T> {
  data: T | null;
  status: Status;
  error: string | null;
  refetch: () => void;
}

export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = []): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);

  const execute = useCallback(() => {
    setStatus("loading");
    setError(null);
    fetcher()
      .then((result) => {
        setData(result);
        setStatus("success");
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Unknown error");
        setStatus("error");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    execute();
  }, [execute]);

  return { data, status, error, refetch: execute };
}
