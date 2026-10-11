import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { Shell } from "@/components/Shell";

beforeEach(() => {
  window.history.replaceState(null, "", "/");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("a logout answered 401 (the session already expired) goes to /login", async () => {
  // No workspaces, so the shell renders its empty state and no screen fetches anything else.
  const replies = [
    { status: 200, body: { user: { id: "u1", email: "ada@example.com" }, workspaces: [] } },
    { status: 401, body: { detail: "log in first" } },
  ];
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => {
    const next = replies.shift();
    if (!next) throw new Error("unexpected fetch");
    return new Response(JSON.stringify(next.body), { status: next.status, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  render(<Shell workspaceId={null} settings={false} />);
  await user.click(await screen.findByRole("button", { name: "Log out" }));
  await waitFor(() => expect(window.location.pathname).toBe("/login"));
  expect(fetchMock.mock.calls[1]![0]).toBe("/api/auth/logout");
  expect(screen.queryByText("log in first")).not.toBeInTheDocument();
});
