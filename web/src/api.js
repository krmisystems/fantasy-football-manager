import { useEffect, useRef, useState } from "react";

export async function request(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    ...options,
  });
  let body;
  try {
    body = await response.json();
  } catch {
    throw new Error("The dashboard returned an unreadable response.");
  }
  if (!response.ok)
    throw new Error(
      typeof body.error === "string"
        ? body.error
        : "The request could not complete.",
    );
  return body;
}

export function post(path, body, csrfToken) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-FFM-CSRF": csrfToken },
    body: JSON.stringify(body),
  });
}

export function useResource(path, revision = 0) {
  const [state, setState] = useState({
    path: null,
    data: null,
    error: null,
    loading: Boolean(path),
  });
  const generation = useRef(0);
  useEffect(() => {
    const id = ++generation.current;
    if (!path) return undefined;
    const controller = new AbortController();
    setState((old) => ({
      path,
      data: old.path === path ? old.data : null,
      error: null,
      loading: true,
    }));
    request(path, { signal: controller.signal }).then(
      (data) => {
        if (id === generation.current)
          setState({ path, data, error: null, loading: false });
      },
      (error) => {
        if (id === generation.current && error.name !== "AbortError")
          setState({ path, data: null, error: error.message, loading: false });
      },
    );
    return () => {
      generation.current += 1;
      controller.abort();
    };
  }, [path, revision]);
  return state.path === path
    ? state
    : { path, data: null, error: null, loading: Boolean(path) };
}

export function useRefreshClock() {
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const refreshVisible = () => {
      if (!document.hidden) setRevision((value) => value + 1);
    };
    const timer = window.setInterval(refreshVisible, 30_000);
    document.addEventListener("visibilitychange", refreshVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refreshVisible);
    };
  }, []);
  return [revision, () => setRevision((value) => value + 1)];
}
