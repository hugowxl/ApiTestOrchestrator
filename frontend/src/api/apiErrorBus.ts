export type ApiErrorPayload = { title: string; message: string };

const listeners = new Set<(p: ApiErrorPayload) => void>();

export function subscribeApiErrors(fn: (p: ApiErrorPayload) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** 由 api client 在请求失败时调用；页面无需再为同一错误重复 setState。 */
export function notifyApiError(message: string, title = "接口请求失败"): void {
  const payload: ApiErrorPayload = { title, message };
  listeners.forEach((fn) => {
    try {
      fn(payload);
    } catch {
      /* ignore subscriber errors */
    }
  });
}
