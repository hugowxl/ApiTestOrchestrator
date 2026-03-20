import { useCallback, useEffect, useId, useRef, useState } from "react";
import { subscribeApiErrors, type ApiErrorPayload } from "../api/apiErrorBus";

export function ApiErrorModalHost() {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [payload, setPayload] = useState<ApiErrorPayload | null>(null);

  const close = useCallback(() => {
    setOpen(false);
    setPayload(null);
  }, []);

  useEffect(() => {
    return subscribeApiErrors((p) => {
      setPayload(p);
      setOpen(true);
    });
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    dialogRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  if (!open || !payload) return null;

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div
        ref={dialogRef}
        className="modal-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <h2 id={titleId} className="modal-title">
          {payload.title}
        </h2>
        <pre className="modal-body">{payload.message}</pre>
        <div className="modal-actions">
          <button type="button" className="btn" onClick={close}>
            确定
          </button>
        </div>
      </div>
    </div>
  );
}
