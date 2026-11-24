import { useCallback, useEffect, useRef, useState } from 'react';

export function useRequest<T>(load: (signal: AbortSignal) => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const current = useRef<AbortController | null>(null);

  const request = useCallback(() => {
    current.current?.abort();
    const controller = new AbortController();
    current.current = controller;
    return Promise.resolve().then(() => load(controller.signal)).then(
      (result) => {
        if (!controller.signal.aborted) {
          setData(result);
          setError(null);
        }
      },
      (failure) => {
        if (!controller.signal.aborted) setError(failure);
      },
    ).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
  }, [load]);

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    return request();
  }, [request]);

  useEffect(() => {
    void request();
    return () => current.current?.abort();
  }, [request]);

  return { data, loading, error, reload };
}
