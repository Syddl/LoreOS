import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { Invite } from "@/screens/Invite";
import { Login } from "@/screens/Login";
import { Signup } from "@/screens/Signup";

const ME = {
  user: { id: "u1", email: "ada@example.com" },
  workspaces: [
    { id: "ws-1", name: "Handbook", role: "owner" },
    { id: "ws-2", name: "Research", role: "member" },
  ],
};

function json(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
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

beforeEach(() => {
  window.history.replaceState(null, "", "/login");
});

// vitest runs without globals, so Testing Library's automatic cleanup is not registered.
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function logIn(password = "correct horse battery") {
  const user = userEvent.setup();
  render(<Login />);
  await user.type(screen.getByLabelText("Email"), "ada@example.com");
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: "Log in" }));
}

test("login shows the server's 401 detail", async () => {
  mockFetch(json({ detail: "wrong email or password" }, 401));
  await logIn("wrong password!");
  expect(await screen.findByRole("alert")).toHaveTextContent("wrong email or password");
  expect(window.location.pathname).toBe("/login");
});

test("login shows how long to wait after a 429", async () => {
  mockFetch(json({ detail: "too many login attempts" }, 429, { "Retry-After": "600" }));
  await logIn();
  expect(await screen.findByRole("alert")).toHaveTextContent("Try again in 10 minutes");
});

test("login moves to the first workspace on success", async () => {
  const fetchMock = mockFetch(json(ME));
  await logIn();
  await waitFor(() => expect(window.location.pathname).toBe("/w/ws-1"));
  expect(fetchMock.mock.calls[0]![0]).toBe("/api/auth/login");
});

test("signup refuses an 11-character password before posting", async () => {
  const fetchMock = mockFetch();
  const user = userEvent.setup();
  window.history.replaceState(null, "", "/signup");
  render(<Signup />);
  await user.type(screen.getByLabelText("Email"), "ada@example.com");
  await user.type(screen.getByLabelText("Password"), "elevenchars");
  await user.click(screen.getByRole("button", { name: "Create account" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("at least 12 characters");
  expect(fetchMock).not.toHaveBeenCalled();
  expect(window.location.pathname).toBe("/signup");
});

test("a logged-out invite accept posts the token from the hash with an email and password", async () => {
  window.history.replaceState(null, "", "/invite#tok-123");
  const fetchMock = mockFetch(json({ detail: "not logged in" }, 401), json({ ...ME, workspaces: [ME.workspaces[1]] }, 201));
  const user = userEvent.setup();
  render(<Invite />);
  await user.type(await screen.findByLabelText("Email"), "ada@example.com");
  await user.type(screen.getByLabelText("Password"), "correct horse battery");
  await user.click(screen.getByRole("button", { name: "Create account and join" }));
  await waitFor(() => expect(window.location.pathname).toBe("/w/ws-2"));
  const [url, init] = fetchMock.mock.calls[1]!;
  expect(url).toBe("/api/invites/accept");
  expect(JSON.parse(init?.body as string)).toEqual({ token: "tok-123", email: "ada@example.com", password: "correct horse battery" });
});

test("a logged-in invite accept posts only the token and opens the joined workspace", async () => {
  window.history.replaceState(null, "", "/invite#tok-123");
  const before = { ...ME, workspaces: [ME.workspaces[0]] };
  const fetchMock = mockFetch(json(before), json(ME));
  const user = userEvent.setup();
  render(<Invite />);
  await user.click(await screen.findByRole("button", { name: "Join workspace" }));
  await waitFor(() => expect(window.location.pathname).toBe("/w/ws-2"));
  expect(JSON.parse(fetchMock.mock.calls[1]![1]?.body as string)).toEqual({ token: "tok-123" });
});
