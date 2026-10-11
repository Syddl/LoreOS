import { afterEach, expect, test, vi } from "vitest";

import { ApiError, acceptInvite, addDocument, deleteDocument, login, me } from "@/api";

function reply(body: BodyInit | null, init: ResponseInit = {}) {
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response(body, init));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

test("a non-2xx throws ApiError with the server's detail and Retry-After", async () => {
  reply(JSON.stringify({ detail: "too many attempts" }), {
    status: 429,
    statusText: "Too Many Requests",
    headers: { "Content-Type": "application/json", "Retry-After": "120" },
  });
  const error = await login("a@example.com", "x").catch((e: unknown) => e);
  expect(error).toBeInstanceOf(ApiError);
  expect(error).toMatchObject({ status: 429, detail: "too many attempts", retryAfter: 120 });
});

test("an error without Retry-After has a null retryAfter", async () => {
  reply(JSON.stringify({ detail: "wrong email or password" }), { status: 401 });
  await expect(login("a@example.com", "x")).rejects.toMatchObject({ status: 401, retryAfter: null });
});

test("a body that is not JSON falls back to the status text", async () => {
  reply("Internal Server Error", { status: 500, statusText: "Internal Server Error", headers: { "Content-Type": "text/plain" } });
  await expect(me()).rejects.toMatchObject({ status: 500, detail: "Internal Server Error" });
});

test("a JSON body sets the content type and sends the cookie", async () => {
  const fetchMock = reply(JSON.stringify({ user: { id: "u", email: "a@example.com" }, workspaces: [] }), { status: 200 });
  await login("a@example.com", "correct horse battery");
  const [url, init] = fetchMock.mock.calls[0]!;
  expect(url).toBe("/api/auth/login");
  expect(init).toMatchObject({ method: "POST", credentials: "same-origin" });
  expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
  expect(JSON.parse(init?.body as string)).toEqual({ email: "a@example.com", password: "correct horse battery" });
});

test("a GET sends no body and no content type", async () => {
  const fetchMock = reply(JSON.stringify({ user: { id: "u", email: "a@example.com" }, workspaces: [] }));
  await me();
  const [url, init] = fetchMock.mock.calls[0]!;
  expect(url).toBe("/api/me");
  expect(init?.body).toBeUndefined();
  expect(new Headers(init?.headers).has("Content-Type")).toBe(false);
});

test("a file upload is multipart, leaving the content type to the browser", async () => {
  const fetchMock = reply(JSON.stringify({ id: "d" }), { status: 202 });
  const file = new File(["# Notes"], "notes.md");
  await addDocument("w1", file);
  const [url, init] = fetchMock.mock.calls[0]!;
  expect(url).toBe("/api/workspaces/w1/documents");
  expect(init?.body).toBeInstanceOf(FormData);
  expect((init?.body as FormData).get("file")).toBeInstanceOf(File);
  expect(new Headers(init?.headers).has("Content-Type")).toBe(false);
});

test("a URL is posted as {url}", async () => {
  const fetchMock = reply(JSON.stringify({ id: "d" }), { status: 202 });
  await addDocument("w1", "https://example.com/handbook");
  expect(JSON.parse(fetchMock.mock.calls[0]![1]?.body as string)).toEqual({ url: "https://example.com/handbook" });
});

test("a 204 resolves with no body", async () => {
  const fetchMock = reply(null, { status: 204 });
  await expect(deleteDocument("w1", "d1")).resolves.toBeUndefined();
  expect(fetchMock.mock.calls[0]).toMatchObject(["/api/workspaces/w1/documents/d1", { method: "DELETE" }]);
});

test("an invite token goes in the body, never in the path", async () => {
  const fetchMock = reply(JSON.stringify({ user: { id: "u", email: "a@example.com" }, workspaces: [] }), { status: 201 });
  await acceptInvite({ token: "secret-token" });
  const [url, init] = fetchMock.mock.calls[0]!;
  expect(url).toBe("/api/invites/accept");
  expect(JSON.parse(init?.body as string)).toEqual({ token: "secret-token" });
});
