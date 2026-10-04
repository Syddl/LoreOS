---
id: 0001
title: Adopt the harness project layer
date: 2026-10-04
status: accepted
superseded_by:
---

# Adopt the harness project layer

## Decision

This repository carries the harness project layer and commits it: a guard hook with zero dependencies, the settings that wire it, a config file that holds every fact the harness reads, a CLAUDE.md of about fifty lines, a path-scoped style rule, this decision log, a known-gaps table and one folder per feature under the sdd root. Procedures come from the harness library loaded per machine. The project never depends on the library at build or CI time.

## Why

Rules kept as prose recur as traps; rules kept as hooks and config do not. Facts kept in one file stop contradicting each other across sessions. A guard that ships with the clone is live before anything is installed.

## Kill switch

Set `HARNESS_HOOKS=off` in the environment to silence the guard for one session. Remove the `hooks` block from `.claude/settings.json` to remove it permanently.

## Reopen only if

The guard blocks legitimate work more than once a week and the pattern cannot be narrowed, or the project moves to a tool that does not run hooks.
