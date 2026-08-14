// API 客户端：同源 cookie 会话为主 + Bearer 兼容注入 + 统一错误处理。
// baseURL 固定 /api（dev 经 Vite proxy 去前缀转发；生产 StaticFiles 同源）
// credentials: include 让 httpOnly cookie 随请求携带
// 401 -> 触发 onUnauthorized 回调（AuthProvider 接管清会话跳登录）

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    public body: unknown
  ) {
    super(detail || `HTTP ${status}`);
    this.name = "ApiError";
  }
}

let authToken: string | null = null;
let unauthorizedHandler: (() => void) | null = null;

export function setToken(token: string | null): void {
  authToken = token;
  if (token) {
    sessionStorage.setItem("calliodesmo.token", token);
  } else {
    sessionStorage.removeItem("calliodesmo.token");
  }
}

export function getToken(): string | null {
  if (authToken) return authToken;
  const cached = sessionStorage.getItem("calliodesmo.token");
  authToken = cached;
  return authToken;
}

export function setUnauthorizedHandler(fn: (() => void) | null): void {
  unauthorizedHandler = fn;
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
  headers?: Record<string, string>;
  query?: Record<string, string | number | boolean | undefined>;
};

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = `/api${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null) params.append(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { ...opts.headers };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.body !== undefined && !(opts.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(buildUrl(path, opts.query), {
    method: opts.method ?? "GET",
    headers,
    credentials: "include",
    body:
      opts.body !== undefined
        ? opts.body instanceof FormData
          ? opts.body
          : JSON.stringify(opts.body)
        : undefined,
    signal: opts.signal,
  });

  if (res.status === 401) {
    setToken(null);
    unauthorizedHandler?.();
    throw new ApiError(401, "未认证或会话已过期", null);
  }
  if (!res.ok) {
    let body: unknown = null;
    let detail = `HTTP ${res.status}`;
    try {
      body = await res.json();
      detail = (body as { detail?: string })?.detail ?? detail;
    } catch {
      /* 无 JSON body */
    }
    throw new ApiError(res.status, detail, body);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  get: <T>(path: string, query?: RequestOptions["query"]) => request<T>(path, { query }),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: "PATCH", body }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: "PUT", body }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  // 文件上传：multipart FormData（自动免 Content-Type，由浏览器带 boundary）
  upload: <T>(path: string, form: FormData) => request<T>(path, { method: "POST", body: form }),
  form: async <T>(path: string, data: URLSearchParams) => {
    const res = await fetch(`/api${path}`, {
      method: "POST",
      body: data,
      credentials: "include",
    });
    if (res.status === 401) {
      setToken(null);
      unauthorizedHandler?.();
      throw new ApiError(401, "用户名或密码错误", null);
    }
    if (!res.ok) {
      throw new ApiError(res.status, `HTTP ${res.status}`, null);
    }
    return (await res.json()) as T;
  },
};
