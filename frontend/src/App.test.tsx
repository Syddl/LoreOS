import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import App from "@/App";

function respondWith(body: unknown, status = 200) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  window.history.replaceState(null, "", "/");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("/ goes to /login when there is no session", async () => {
  respondWith({ detail: "not logged in" }, 401);
  render(<App />);
  expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
  expect(window.location.pathname).toBe("/login");
});

test("/ opens the first workspace, with Documents and Ask", async () => {
  respondWith({
    user: { id: "u1", email: "ada@example.com" },
    workspaces: [
      { id: "ws-1", name: "Handbook", role: "member" },
      { id: "ws-2", name: "Research", role: "owner" },
    ],
  });
  render(<App />);
  await waitFor(() => expect(window.location.pathname).toBe("/w/ws-1"));
  expect(await screen.findByRole("button", { name: "Workspace: Handbook" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Documents" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Ask" })).toBeInTheDocument();
  // A member sees no settings link.
  expect(screen.queryByRole("link", { name: "Settings" })).not.toBeInTheDocument();
});

test("an owner's settings path shows Settings", async () => {
  window.history.replaceState(null, "", "/w/ws-2/settings");
  respondWith({ user: { id: "u1", email: "ada@example.com" }, workspaces: [{ id: "ws-2", name: "Research", role: "owner" }] });
  render(<App />);
  expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
});
