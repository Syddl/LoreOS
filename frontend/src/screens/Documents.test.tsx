import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import type { Document } from "@/api";
import { Documents } from "@/screens/Documents";

const LIST = "/api/workspaces/ws-1/documents";

function doc(over: Partial<Document> = {}): Document {
  return {
    id: "d1",
    filename: "handbook.md",
    kind: "md",
    status: "processed",
    error: null,
    attempts: 1,
    chunk_count: 12,
    created_at: "2026-10-01T09:00:00Z",
    processed_at: "2026-10-01T09:00:05Z",
    ...over,
  };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function mockFetch(...responses: Response[]) {
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => {
    const next = responses.shift();
    if (!next) throw new Error("unexpected fetch");
    return next;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

// Only the poll's interval is fake, so Testing Library's waitFor and userEvent keep their real setTimeout.
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  window.history.replaceState(null, "", "/w/ws-1");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const tick = () => act(() => vi.advanceTimersByTimeAsync(2000));

test("a failed document shows its error", async () => {
  mockFetch(json([doc({ status: "failed", chunk_count: 0, error: "parse: the PDF has no text layer" })]));
  render(<Documents workspaceId="ws-1" role="member" />);
  expect(await screen.findByText("parse: the PDF has no text layer")).toBeInTheDocument();
  expect(screen.getByText("Failed")).toBeInTheDocument();
});

test("delete appears only for an owner", async () => {
  mockFetch(json([doc()]));
  const { unmount } = render(<Documents workspaceId="ws-1" role="member" />);
  expect(await screen.findByText("handbook.md")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /delete/i })).not.toBeInTheDocument();
  unmount();

  mockFetch(json([doc()]));
  render(<Documents workspaceId="ws-1" role="owner" />);
  expect(await screen.findByRole("button", { name: "Delete handbook.md" })).toBeInTheDocument();
});

test("delete asks first, then shows a 409's detail", async () => {
  const fetchMock = mockFetch(json([doc()]), json({ detail: "the document is being processed; try again shortly" }, 409));
  const user = userEvent.setup();
  render(<Documents workspaceId="ws-1" role="owner" />);
  await user.click(await screen.findByRole("button", { name: "Delete handbook.md" }));
  expect(fetchMock).toHaveBeenCalledTimes(1);
  await user.click(screen.getByRole("button", { name: "Delete document" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("the document is being processed; try again shortly");
  const [url, init] = fetchMock.mock.calls[1]!;
  expect(url).toBe(`${LIST}/d1`);
  expect(init?.method).toBe("DELETE");
});

test("a URL submit posts {url}", async () => {
  const page = doc({ id: "d2", filename: "https://example.com/faq", kind: "url", status: "pending", chunk_count: 0 });
  const fetchMock = mockFetch(json([]), json(page, 202));
  const user = userEvent.setup();
  render(<Documents workspaceId="ws-1" role="member" />);
  await user.type(await screen.findByLabelText("Web page URL"), "https://example.com/faq");
  await user.click(screen.getByRole("button", { name: "Add page" }));
  expect(await screen.findByText("https://example.com/faq")).toBeInTheDocument();
  const [url, init] = fetchMock.mock.calls[1]!;
  expect(url).toBe(LIST);
  expect(init?.method).toBe("POST");
  expect(JSON.parse(init?.body as string)).toEqual({ url: "https://example.com/faq" });
});

test("polling stops once every document has settled", async () => {
  const fetchMock = mockFetch(
    json([doc({ status: "pending", chunk_count: 0 })]),
    json([doc({ status: "processing", chunk_count: 0 })]),
    json([doc({ status: "processed" })]),
  );
  render(<Documents workspaceId="ws-1" role="member" />);
  expect(await screen.findByText("Queued")).toBeInTheDocument();
  await tick();
  expect(await screen.findByText("Processing")).toBeInTheDocument();
  await tick();
  expect(await screen.findByText("Ready")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(3);
  await tick();
  await tick();
  await tick();
  expect(fetchMock).toHaveBeenCalledTimes(3);
  expect(fetchMock.mock.calls.every(([url]) => url === LIST)).toBe(true);
});

test("a 413 shows its detail", async () => {
  const fetchMock = mockFetch(json([]), json({ detail: "the file is over 20 MB; split it or upload a smaller file" }, 413));
  const user = userEvent.setup();
  render(<Documents workspaceId="ws-1" role="member" />);
  await user.upload(await screen.findByLabelText("Upload a file"), new File(["# big"], "big.md", { type: "text/markdown" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("the file is over 20 MB");
  const body = fetchMock.mock.calls[1]![1]?.body;
  expect(body).toBeInstanceOf(FormData);
  expect((body as FormData).get("file")).toHaveProperty("name", "big.md");
});

test("a 401 in the middle of a session goes to /login", async () => {
  mockFetch(json([doc({ status: "processing", chunk_count: 0 })]), json({ detail: "not logged in" }, 401));
  render(<Documents workspaceId="ws-1" role="member" />);
  expect(await screen.findByText("Processing")).toBeInTheDocument();
  await tick();
  await waitFor(() => expect(window.location.pathname).toBe("/login"));
});
