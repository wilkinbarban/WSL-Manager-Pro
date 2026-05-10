# ADR 0001: QProcess vs subprocess

## Status
Accepted

## Context
`WSL Manager Pro` already uses Qt workers plus Python `subprocess` for streaming
output from `wsl.exe`, PowerShell, and `winget`. The current model is stable,
testable in isolation, and already supports log streaming without blocking the UI.

## Decision
Keep `subprocess` as the default process backend for now.

## Reasons
- Existing workers already provide non-blocking behavior through `QThread`.
- A broad migration to `QProcess` would touch many install, repair, and shell
  flows with higher regression risk than value for this phase.
- `subprocess` keeps the engine layer decoupled from Qt and easier to unit-test.

## Consequences
- We do not adopt `QProcess` globally in this roadmap slice.
- Future targeted adoption is still possible for a single flow if cancellation or
  signal integration becomes meaningfully better than the current worker model.
