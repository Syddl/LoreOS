## Report: fix wave 4, review findings 13 and 14 (p4-platform-shell, step 10)

Setup: `git merge --ff-only p4-platform-shell` moved this branch from faa149c to `a2cb7e7`. I then ran `npm ci --prefix frontend` as a real install with no junction, and it exited 0. Both fixes are in commit `14af149`, `fix(p4): logout after expiry goes to /login, and the invite token leaves history (review findings 13, 14)`, which has no attribution trailer.

## Files touched

| File | Change |
|---|---|
| `frontend/src/components/Shell.tsx` | edited: `onLogout` treats an `ApiError` with status 401 as logged out and goes to `/login`. Any other error is still shown. |
| `frontend/src/screens/Invite.tsx` | edited: the token is read once into state (`useState(() => location.hash.slice(1))`). An effect on mount then calls `history.replaceState(null, "", pathname + search)`. |
| `frontend/src/components/Shell.test.tsx` | added: the case "a logout answered 401 goes to /login". |
| `frontend/src/screens/Login.test.tsx` | edited: added the case "the invite drops the token from the address bar once read, and accept still posts it". |

## Old vs new

| Behaviour | Before | After |
|---|---|---|
| Log out after the session has expired (logout returns 401) | Stays on the page and shows the alert "log in first" | Goes to `/login` with no alert |
| Log out that fails with any other error | Shows the error | Unchanged |
| Opening `/invite#<token>` | The token stays in the address bar and in the session-history entry | The hash is empty once the screen mounts and the path stays `/invite`. Accept still posts the token from state. |

`logout()` has only one caller (Shell), so the guard sits there.

## How tested

Red before the fix (`npm --prefix frontend test`):
```
FAIL src/components/Shell.test.tsx > a logout answered 401 ...
Expected: "/login"   Received: "/"     (the DOM shows the alert "log in first")
FAIL src/screens/Login.test.tsx > the invite drops the token from the address bar once read, and accept still posts it
AssertionError: expected '#tok' to be ''   at Login.test.tsx:102
Test Files  2 failed | 5 passed (7)
     Tests  2 failed | 36 passed (38)
```
Green after the fix:
```
npm --prefix frontend test
 Test Files  7 passed (7)
      Tests  38 passed (38)

npm run check:frontend
> tsc -b            (clean)
 Test Files  7 passed (7)
      Tests  38 passed (38)
> vite build        ✓ built in 754ms
check:frontend: typecheck, tests and build pass
```
Red-proof, run after the commit. The mutation replaced the `replaceState(...)` call with nothing:
```
node .../redproof.mjs --project . --check "npm --prefix frontend test" --file frontend/src/screens/Invite.tsx
  --find 'window.history.replaceState(null, "", window.location.pathname + window.location.search);' --replace ''
  --expect "the invite drops the token from the address bar once read"
  red  npm --prefix frontend test exited 1 with the mutation (expected)
  ok   the red output contains "the invite drops the token from the address bar once read"
       + #tok   at src/screens/Login.test.tsx:102:32  expect(window.location.hash).toBe("")
       Tests  1 failed | 37 passed (38)
  ok   restored byte-identical
  green npm --prefix frontend test exited 0 after restore
redproof: PASS
```
The working tree is clean afterwards. `dist` and `*.tsbuildinfo` are gitignored and were not staged. The only files staged were the four above, checked with `git diff --cached --name-only`.

What the new checks do not exercise:
- The Shell case covers an account with no workspaces, so Documents and Ask do not mount. The logout code is the same with a workspace open.
- There is no red-proof run for the Shell fix. Its proof is the red run above, taken before the fix.

## Limitations

- **Session history only.** Both tests run in jsdom. `replaceState` swaps the current session-history entry, so the back button never shows `/invite#<token>`. It is not proven in a real browser that the browser's global history (the visited-URL list and autocomplete) leaves out the URL first loaded. That needs a manual check in Chrome and Firefox.
- **StrictMode.** In dev, StrictMode runs the state initializer twice. Both runs happen during render, before the effect clears the hash, so the token survives. This was reasoned through, not tested: vitest renders without StrictMode.
- **Same-page link.** Following a second invite link while `/invite` is already open is not handled, because the token is read only on mount. The current screens offer no way to do that.

## Findings outside the owned files

- None.
