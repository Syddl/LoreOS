import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// vitest runs without globals, so Testing Library cannot register its own cleanup: unmount after every test here.
afterEach(cleanup);
