# Report: fix wave 3, review finding 4 (Secure session cookie behind a TLS proxy)

The fix is committed as `52f854d` on `worktree-agent-a6f1cc0b5ee844b69`, fast-forwarded from `a2cb7e7`. The new test failed before the fix and passes after it, `npm run check:backend` passes in full, and redproof passes. The working tree is clean.

## Files touched

| File | Change |
|---|---|
| `backend/loreos/auth.py` | Edited. `set_session_cookie` now sets `secure` when the request URL scheme or the `Origin` header scheme is https. Adds the `urllib.parse.urlsplit` import, and the docstring explains why. |
| `backend/tests/test_auth.py` | Added one test, `test_a_login_over_http_whose_origin_is_https_gets_a_secure_cookie`. |

## Old vs new

| Behaviour | Before | After |
|---|---|---|
| Login over http with an `https://<host>` Origin (a TLS proxy uvicorn does not trust) | Cookie not `Secure` | Cookie `Secure` |
| Login over http with an `http://` Origin (local dev) | Not `Secure` | Not `Secure` (unchanged) |
| https base URL | `Secure` | `Secure` (unchanged) |

The fix sits in the one function that all three callers use (login, signup and invite accept in `routes/auth.py`), so all three get it. If there is no Origin header, the scheme reads as empty and the result falls back to the URL scheme.

## How tested

Red before the fix:
```
uv --directory backend run python -m pytest tests/test_auth.py
>       assert bool(SimpleCookie(response.headers["set-cookie"])[auth.SESSION_COOKIE]["secure"]) is True
E       AssertionError: assert False is True
FAILED tests/test_auth.py::test_a_login_over_http_whose_origin_is_https_gets_a_secure_cookie
1 failed, 116 passed in 76.95s
```
Green after the fix. This includes the existing `test_login_sets_the_session_cookie_with_its_flags[http|https]` (http with an http Origin stays non-Secure, https gets Secure) and `test_the_session_cookie_flags[http|https]`:
```
uv --directory backend run python -m pytest tests/test_auth.py
117 passed in 70.79s
```
Full backend check:
```
npm run check:backend
693 passed, 2 skipped in 240.50s   (EXIT=0)
```
Redproof, run after the commit. The mutation drops the Origin condition:
```
redproof: backend/loreos/auth.py :: "https = \"https\" in (request.url.scheme, urlsplit(request.headers.get(\"origin\", \"\")).scheme)" -> "https = \"https\" in (request.url.scheme,)"
  red  ... exited 1 with the mutation (expected)
  ok   the red output contains "test_a_login_over_http_whose_origin_is_https_gets_a_secure_cookie"
       | FAILED tests/test_auth.py::test_a_login_over_http_whose_origin_is_https_gets_a_secure_cookie
       | 1 failed, 116 passed in 66.29s
  ok   restored byte-identical
  green ... exited 0 after restore
redproof: PASS
```
The new test covers login only. Signup and invite accept get the same behaviour through the same function, but no test covers them separately.

## Limitations

- No browser or real proxy was used. The test simulates the proxy with a TestClient whose base URL is http and whose Origin is https. A real deployment with compose behind a TLS proxy and no `FORWARDED_ALLOW_IPS` has not been exercised. Logging in through such a proxy and checking that `Set-Cookie` contains `Secure` would prove it.
- An http request that sends an https Origin now gets a Secure cookie, and the browser will then not send that cookie back over plain http. This only happens when the Origin's host:port matches Host, which the Origin rule enforces, so in practice it is the proxy case the fix is for.
- Only `check:backend` was run. `check:all` (frontend, licenses, hooks) was not, and this change does not touch anything those checks read.

## Findings outside the owned files

- `docs/sdd/p4-platform-shell/spec.md:66` (behaviour 7) still says the cookie is `Secure` only "when the request arrived over HTTPS, as uvicorn reports it from `--proxy-headers` and `FORWARDED_ALLOW_IPS`". It should add "or when its Origin is https". Owner: dispatcher.
- `docs/KNOWN-GAPS.md:9`: the review asked for the cookie impact to be added to this row as the alternative fix. With this fix in place, the row needs no cookie note, though it may still be worth saying that `X-Forwarded-Proto` is otherwise untrusted. Owner: dispatcher.
