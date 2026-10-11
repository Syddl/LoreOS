import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import App from "@/App";

test("the app renders into the page", () => {
  render(<App />);
  expect(screen.getByRole("main")).toHaveTextContent("LoreOS");
});
