// One function per route of the HTTP contract in docs/sdd/p4-platform-shell/plan.md.
// Every non-2xx throws ApiError; the session rides on the same-origin cookie.

export type Role = "owner" | "member";
export type Workspace = { id: string; name: string; role: Role };
export type Me = { user: { id: string; email: string }; workspaces: Workspace[] };
export type DocumentStatus = "pending" | "processing" | "processed" | "failed";
export type Document = {
  id: string;
  filename: string;
  kind: string;
  status: DocumentStatus;
  error: string | null;
  attempts: number;
  chunk_count: number;
  created_at: string;
  processed_at: string | null;
};
export type Citation = {
  n: number;
  chunk_id: string;
  document_id: string;
  filename: string;
  heading_path: string[];
  page: number | null;
  text: string;
};
export type Answer = { found: boolean; answer: string; reason: string | null; citations: Citation[] };
export type Member = { user_id: string; email: string; role: Role };
export type Invite = { created_at: string; expires_at: string; created_by: string | null };
export type CreatedInvite = { token: string; expires_at: string };
export type ApiKey = {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
};
export type CreatedKey = { id: string; name: string; prefix: string; key: string; created_at: string };

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  /** Seconds from the Retry-After header; null when absent or not a number. */
  readonly retryAfter: number | null;

  constructor(status: number, detail: string, retryAfter: number | null) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.retryAfter = retryAfter;
  }
}

/** The server's rule (auth.MIN_PASSWORD, a 422 below it), mirrored so a short password fails before posting. */
export const MIN_PASSWORD = 12;
/** Counts code points, as the server's len() does, so an emoji counts once. */
export const passwordTooShort = (password: string) => [...password].length < MIN_PASSWORD;

/** The text to show for a failed call: the server's detail, or what to do when the server was never reached. */
export function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.detail;
  // fetch rejects with a TypeError only when the request never got a response.
  if (error instanceof TypeError) return "Could not reach LoreOS. Check your connection and try again.";
  return error instanceof Error ? error.message : String(error);
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin" };
  if (body instanceof FormData) {
    init.body = body; // the browser sets the multipart boundary
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { "Content-Type": "application/json" };
  }
  const res = await fetch(path, init);
  if (!res.ok) {
    // A plain-text 500 or 503 has no {detail}, and HTTP/2 sends no status text.
    let detail = res.statusText || `Request failed with status ${res.status}`;
    try {
      const data: unknown = await res.json();
      if (data && typeof data === "object" && "detail" in data && typeof data.detail === "string") detail = data.detail;
    } catch {
      // not JSON: keep the status text
    }
    const header = res.headers.get("Retry-After");
    const seconds = Number(header);
    throw new ApiError(res.status, detail, header && Number.isFinite(seconds) ? seconds : null);
  }
  return (res.status === 204 ? undefined : await res.json()) as T;
}

const ws = (workspaceId: string) => `/api/workspaces/${workspaceId}`;

export const signup = (email: string, password: string, workspace_name?: string) =>
  request<Me>("POST", "/api/auth/signup", { email, password, workspace_name });
export const login = (email: string, password: string) => request<Me>("POST", "/api/auth/login", { email, password });
export const logout = () => request<void>("POST", "/api/auth/logout");
export const me = () => request<Me>("GET", "/api/me");
/** Logged out: {token, email, password} creates the account. Logged in: {token} joins as the current user. */
export const acceptInvite = (body: { token: string } | { token: string; email: string; password: string }) =>
  request<Me>("POST", "/api/invites/accept", body);

export const listWorkspaces = () => request<Workspace[]>("GET", "/api/workspaces");
export const createWorkspace = (name: string) => request<Workspace>("POST", "/api/workspaces", { name });

export const listMembers = (w: string) => request<Member[]>("GET", `${ws(w)}/members`);
export const removeMember = (w: string, userId: string) => request<void>("DELETE", `${ws(w)}/members/${userId}`);
export const createInvite = (w: string) => request<CreatedInvite>("POST", `${ws(w)}/invites`);
export const listInvites = (w: string) => request<Invite[]>("GET", `${ws(w)}/invites`);
export const createApiKey = (w: string, name: string) => request<CreatedKey>("POST", `${ws(w)}/api-keys`, { name });
export const listApiKeys = (w: string) => request<ApiKey[]>("GET", `${ws(w)}/api-keys`);
export const revokeApiKey = (w: string, keyId: string) => request<void>("DELETE", `${ws(w)}/api-keys/${keyId}`);

/** A File is uploaded as multipart field "file"; a string is fetched by the server as {url}. */
export function addDocument(w: string, source: File | string) {
  let body: FormData | { url: string };
  if (typeof source === "string") {
    body = { url: source };
  } else {
    body = new FormData();
    body.append("file", source);
  }
  return request<Document>("POST", `${ws(w)}/documents`, body);
}
export const listDocuments = (w: string) => request<Document[]>("GET", `${ws(w)}/documents`);
export const getDocument = (w: string, id: string) => request<Document>("GET", `${ws(w)}/documents/${id}`);
export const deleteDocument = (w: string, id: string) => request<void>("DELETE", `${ws(w)}/documents/${id}`);
export const ask = (w: string, question: string) => request<Answer>("POST", `${ws(w)}/ask`, { question });
