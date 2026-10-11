---
id: 0007
title: MPL-2.0 dependencies are allowed when unmodified
date: 2026-10-11
status: accepted
superseded_by:
---

# MPL-2.0 dependencies are allowed when unmodified

## Decision

A dependency under MPL-2.0 is allowed when LoreOS uses it unmodified. AGPL, GPL and LGPL stay refused. This narrows the AGENTS.md rule "No dependency under AGPL or another copyleft license", and `check:licenses` enforces the narrowed rule.

Known cases:
- `lightningcss`, a direct dependency of Vite 8 and Tailwind 4. It is used at build time only and never ships in the runtime image.
- `tqdm` (MPL-2.0 AND MIT), pulled in by fastembed for P3's reranker. It ships in the image.

## Why

The operator chose this on 2026-10-11.

MPL-2.0 is file-level copyleft. Its terms bind changes to the MPL-covered files themselves and nothing else. Used unmodified, it leaves LoreOS distributable under MIT.

The strict rule would mean pinning an older toolchain, Tailwind 3 on PostCSS and a Vite without lightningcss, and finding a reranker path without tqdm, for no change in what LoreOS's license allows.

## Kill switch

None. It is a policy, enforced by `check:licenses`.

## Reopen only if

- LoreOS needs to patch an MPL-2.0 dependency. The patched files would then be published under MPL-2.0.
- A dependency arrives under a stronger copyleft license.
