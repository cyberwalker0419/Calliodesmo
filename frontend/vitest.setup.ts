import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

/**
 * Node 26 + jsdom 25 在不透明 origin 下不提供 localStorage / sessionStorage；
 * 测试基建在此提供内存实现（浏览器行为等价），避免 setup teardown 抛错。
 */
function ensureStorage(name: "localStorage" | "sessionStorage"): void {
  try {
    if (window[name]) return;
  } catch {
    /* 访问即抛（不透明 origin）时回退内存实现 */
  }
  const store = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (key: string) => store.get(key) ?? null,
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    removeItem: (key: string) => void store.delete(key),
    setItem: (key: string, value: string) => void store.set(key, String(value)),
  };
  Object.defineProperty(window, name, { value: storage, configurable: true });
}

ensureStorage("localStorage");
ensureStorage("sessionStorage");

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.sessionStorage.clear();
  vi.restoreAllMocks();
});
