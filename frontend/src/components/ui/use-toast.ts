import { useSyncExternalStore } from "react";

export type ToastVariant = "default" | "destructive";
export interface Toast {
  id: string;
  title?: string;
  description?: string;
  variant?: ToastVariant;
}

type Listener = () => void;
let toasts: Toast[] = [];
const listeners = new Set<Listener>();

function emit() {
  toasts = [...toasts];
  listeners.forEach((l) => l());
}

export function toast(t: Omit<Toast, "id">) {
  const id = Math.random().toString(36).slice(2);
  toasts = [...toasts, { ...t, id }];
  emit();
  setTimeout(() => dismiss(id), 5000);
  return id;
}

export function dismiss(id: string) {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}

function subscribe(l: Listener) {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}
function getSnapshot() {
  return toasts;
}

export function useToast() {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}