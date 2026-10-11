import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import type { Answer } from "@/api";
import { Ask } from "@/screens/Ask";

// Citations numbered 2 and 4, as the answerer numbers them: position in the list is not the marker number.
const ANSWER: Answer = {
  found: true,
  answer: "Parental leave is 16 weeks [2]. Leave dates are agreed with your lead [3], in writing [4].",
  reason: null,
  citations: [
    {
      n: 2,
      chunk_id: "c-2",
      document_id: "d-1",
      filename: "handbook.md",
      heading_path: ["Leave", "Parental leave"],
      page: null,
      text: "Employees receive 16 weeks of paid parental leave.",
    },
    {
      n: 4,
      chunk_id: "c-4",
      document_id: "d-2",
      filename: "policy.pdf",
      heading_path: [],
      page: 7,
      text: "Requests for leave are confirmed by email.",
    },
  ],
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function mockFetch(response: Response) {
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  window.history.replaceState(null, "", "/w/ws-1");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function askQuestion(response: Response) {
  const fetchMock = mockFetch(response);
  const user = userEvent.setup();
  render(<Ask workspaceId="ws-1" />);
  await user.type(screen.getByLabelText("Question"), "How long is parental leave?");
  await user.click(screen.getByRole("button", { name: "Ask" }));
  return { fetchMock, user };
}

test("[4] opens citation 4's filename and passage, whatever its position in the list", async () => {
  const { fetchMock, user } = await askQuestion(json(ANSWER));
  // In answer order: [2] is the first marker and [4] the second, so a lookup by position cannot pass.
  const markers = await screen.findAllByRole("button", { name: /^Source \d+$/ });
  expect(markers.map((m) => m.getAttribute("aria-label"))).toEqual(["Source 2", "Source 4"]);
  await user.click(screen.getByRole("button", { name: "Source 4" }));
  const panel = await screen.findByRole("dialog");
  expect(within(panel).getByText("policy.pdf")).toBeInTheDocument();
  expect(within(panel).getByText("page 7")).toBeInTheDocument();
  expect(within(panel).getByText("Requests for leave are confirmed by email.")).toBeInTheDocument();
  expect(within(panel).queryByText("handbook.md")).not.toBeInTheDocument();

  const [url, init] = fetchMock.mock.calls[0]!;
  expect(url).toBe("/api/workspaces/ws-1/ask");
  expect(JSON.parse(init?.body as string)).toEqual({ question: "How long is parental leave?" });
});

test("[3] has no citation, so it stays as text and is not a button", async () => {
  await askQuestion(json(ANSWER));
  expect(await screen.findByRole("button", { name: "Source 2" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Source 3" })).not.toBeInTheDocument();
  expect(screen.getByText(/agreed with your lead \[3\], in writing/)).toBeInTheDocument();
});

test("the panel takes focus, shows the heading path, and Escape returns focus to the marker", async () => {
  const { user } = await askQuestion(json(ANSWER));
  const marker = await screen.findByRole("button", { name: "Source 2" });
  await user.click(marker);
  const panel = await screen.findByRole("dialog");
  expect(within(panel).getByText("Leave > Parental leave")).toBeInTheDocument();
  expect(panel).toContainElement(document.activeElement as HTMLElement);

  await user.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(marker).toHaveFocus();
});

test("found: false renders the refusal as plain text, with no source buttons", async () => {
  const refusal = "I couldn't find this in your documents.";
  await askQuestion(json({ found: false, answer: refusal, reason: "no_chunks", citations: [] }));
  expect(await screen.findByText(refusal)).toBeInTheDocument();
  expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["Ask"]);
});

test("a 401 in the middle of a session goes to /login", async () => {
  await askQuestion(json({ detail: "not logged in" }, 401));
  await waitFor(() => expect(window.location.pathname).toBe("/login"));
});
