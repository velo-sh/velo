# DEF-13-007: Zygote CLI missing `--daemon` flag for start command

## Status
- **Priority**: P1 (Critical for performance, breaks Zygote integration)
- **Severity**: Major
- **Category**: CLI / Integration
- **Reporter**: QA Agent (Antigravity)
- **Status**: **OPEN**

## Description
The `pytest-velo` plugin attempts to start the Zygote server using the command:
`velo zygote start --daemon`

However, the current Rust CLI implementation for the `zygote start` subcommand does not define or handle the `--daemon` flag. This causes the Zygote startup to fail during `pytest_configure`, producing the following warning:

```text
RuntimeWarning: Failed to start Zygote: error: unexpected argument '--daemon' found
  
Usage: zygote start [OPTIONS]
```

## Impact
Because the Zygote fails to start via the CLI, the plugin falls back to a non-accelerated mode. 
- **Performance Loss**: Speedups drop from ~42x (Zygote mode) to ~1x (Standard mode).
- **Integration Failure**: The core value proposition of Phase 13 (Hyper-Loop acceleration) is disabled by default when running via `pytest`.

## Reproduction Steps
1. Build the current `velo` binary.
2. Run any project with `pytest --velo`.
3. Observe the `RuntimeWarning` and the lack of "Zygote" mentions in the output.
4. Manually verify via CLI: `./target/release/velo zygote start --daemon` (will fail).

## Proposed Fix
Update `src/cmd/zygote.rs`:
1. Add `daemon: bool` flag to the `Start` variant of `ZygoteSubcommand`.
2. Pass the `daemon` boolean to `cmd_zygote_start`.
3. Update `cmd_zygote_start` to pass this flag to `launcher.start(&preload, None, daemon, &config)`.

---
**QA Note**: Reverted local fix as per USER policy to focus on testing. Submitted for developer repair.
