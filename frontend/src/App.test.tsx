import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import App from "@/App";
import { navigate } from "@/router";

// /api/me gets `body` (and so does every call when status is an error); the screens' list calls get [].
function respondWith(body: unknown, status = 200) {
  const fetchMock = vi.fn(async (url: string) => {
    const reply = status !== 200 || url === "/api/me" ? body : [];
    return new Response(JSON.stringify(reply), { status, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  window.history.replaceState(null, "", "/");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
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

test("switching workspace replaces the screens, never stacks them", async () => {
  const errors = vi.spyOn(console, "error").mockImplementation(() => {});
  respondWith({
    user: { id: "u1", email: "ada@example.com" },
    workspaces: [
      { id: "ws-1", name: "Handbook", role: "owner" },
      { id: "ws-2", name: "Research", role: "owner" },
      { id: "ws-3", name: "Legal", role: "owner" },
    ],
  });
  render(<App />);
  await waitFor(() => expect(window.location.pathname).toBe("/w/ws-1"));
  await screen.findByRole("button", { name: "Workspace: Handbook" });
  for (const id of ["ws-2", "ws-3", "ws-1"]) {
    act(() => navigate(`/w/${id}`));
    await waitFor(() => expect(window.location.pathname).toBe(`/w/${id}`));
  }
  expect(screen.getAllByRole("heading", { name: "Documents" })).toHaveLength(1);
  expect(screen.getAllByRole("heading", { name: "Ask" })).toHaveLength(1);
  expect(errors.mock.calls.flat().join(" ")).not.toMatch(/same key/);
});

test("an owner's settings path shows Settings", async () => {
  window.history.replaceState(null, "", "/w/ws-2/settings");
  respondWith({ user: { id: "u1", email: "ada@example.com" }, workspaces: [{ id: "ws-2", name: "Research", role: "owner" }] });
  render(<App />);
  expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
});
