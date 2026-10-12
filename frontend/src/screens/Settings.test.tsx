import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { Settings } from "@/screens/Settings";

const W = "/api/workspaces/ws-1";
const MEMBERS = [
  { user_id: "u1", email: "ada@example.com", role: "owner" },
  { user_id: "u2", email: "bob@example.com", role: "member" },
];
const KEYS = [
  { id: "key-1", name: "CI", prefix: "abcd1234", created_at: "2026-10-01T09:00:00Z", last_used_at: null, revoked_at: null },
  {
    id: "key-2",
    name: "Old bot",
    prefix: "zyxw9876",
    created_at: "2026-09-01T09:00:00Z",
    last_used_at: "2026-09-20T09:00:00Z",
    revoked_at: "2026-10-05T09:00:00Z",
  },
];

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** A fake api keyed by "METHOD path": the three lists load by default, and each test adds the calls it makes. */
function serve(routes: Record<string, () => Response> = {}) {
  const all: Record<string, () => Response> = {
    [`GET ${W}/members`]: () => json(MEMBERS),
    [`GET ${W}/invites`]: () => json([]),
    [`GET ${W}/api-keys`]: () => json(KEYS),
    ...routes,
  };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const route = all[`${init?.method ?? "GET"} ${url}`];
    if (!route) throw new Error(`unexpected ${init?.method} ${url}`);
    return route();
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  window.history.replaceState(null, "", "/w/ws-1/settings");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("the invite link is built from window.location.origin with the token in the # fragment", async () => {
  const fetchMock = serve({ [`POST ${W}/invites`]: () => json({ token: "tok-abc", expires_at: "2026-10-18T09:00:00Z" }, 201) });
  const user = userEvent.setup();
  render(<Settings workspaceId="ws-1" />);
  await user.click(await screen.findByRole("button", { name: "Create invite link" }));

  const link = `${window.location.origin}/invite#tok-abc`;
  expect(await screen.findByLabelText("Invite link")).toHaveValue(link);
  await user.click(screen.getByRole("button", { name: "Copy invite link" }));
  expect(await navigator.clipboard.readText()).toBe(link);
  expect(fetchMock.mock.calls.map(([url]) => url).filter((url) => url.includes("tok-abc"))).toEqual([]);
});

test("a created key shows once: gone after dismiss, after a re-render and after a reload", async () => {
  const KEY = "lo_sk_SECRETsecretSECRETsecretSECRETsecret123";
  const fetchMock = serve({
    [`POST ${W}/api-keys`]: () => json({ id: "key-3", name: "Deploy", prefix: "SECRETse", key: KEY, created_at: "2026-10-11T09:00:00Z" }, 201),
  });
  const shown = () => screen.queryByDisplayValue(KEY) ?? screen.queryByText(KEY, { exact: false });
  const user = userEvent.setup();
  const { rerender, unmount } = render(<Settings workspaceId="ws-1" />);

  await user.type(await screen.findByLabelText("Key name"), "Deploy");
  await user.click(screen.getByRole("button", { name: "Create key" }));
  expect(await screen.findByLabelText("New API key")).toHaveValue(KEY);
  const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")!;
  expect(JSON.parse(post[1]!.body as string)).toEqual({ name: "Deploy" });
  // The list gains the key by its prefix only.
  expect(screen.getByText("Deploy").closest("tr")).toHaveTextContent("SECRETse");

  await user.click(screen.getByRole("button", { name: "Hide key" }));
  expect(shown()).toBeNull();
  rerender(<Settings workspaceId="ws-1" />);
  expect(shown()).toBeNull();

  unmount();
  render(<Settings workspaceId="ws-1" />);
  await screen.findByText("CI");
  expect(shown()).toBeNull();
});

test("revoke sends DELETE api-keys/{id}, and a revoked key offers no revoke", async () => {
  const fetchMock = serve({ [`DELETE ${W}/api-keys/key-1`]: () => new Response(null, { status: 204 }) });
  const user = userEvent.setup();
  render(<Settings workspaceId="ws-1" />);

  expect(await screen.findByText("Old bot")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Revoke Old bot" })).toBeNull();
  expect(screen.getByText("Old bot").closest("tr")).toHaveTextContent("Revoked");

  await user.click(screen.getByRole("button", { name: "Revoke CI" }));
  await waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(`${W}/api-keys/key-1`, expect.objectContaining({ method: "DELETE" })),
  );
});

test("a 409 on removing the last owner shows its detail and keeps the member", async () => {
  serve({ [`DELETE ${W}/members/u1`]: () => json({ detail: "a workspace must keep at least one owner" }, 409) });
  const user = userEvent.setup();
  render(<Settings workspaceId="ws-1" />);

  await user.click(await screen.findByRole("button", { name: "Remove ada@example.com" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("a workspace must keep at least one owner");
  expect(screen.getByText("ada@example.com")).toBeInTheDocument();
});

test("a 401 from an action in the middle of a session navigates to /login", async () => {
  serve({ [`POST ${W}/invites`]: () => json({ detail: "not logged in" }, 401) });
  const user = userEvent.setup();
  render(<Settings workspaceId="ws-1" />);

  await user.click(await screen.findByRole("button", { name: "Create invite link" }));
  await waitFor(() => expect(window.location.pathname).toBe("/login"));
});

test("a 401 while loading navigates to /login", async () => {
  serve({ [`GET ${W}/members`]: () => json({ detail: "not logged in" }, 401) });
  render(<Settings workspaceId="ws-1" />);
  await waitFor(() => expect(window.location.pathname).toBe("/login"));
});
