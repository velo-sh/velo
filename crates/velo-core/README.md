# Velo Core (`velo-core`)

The heart of the Velo Native Distribution Platform. This crate contains the core logic for the Zygote process, security shielding, and environment management.

## Role in 4-Crate Architecture

- **`velo-core`**: Core safety and lifecycle logic.
- **`velo-serve`**: Request handling and worker coordination.
- **`velo-cli`**: User-facing command line interface.
- **`velo-test`**: Integration testing infrastructure.

## Key Components

### V-Shield (Security Shield)
Implemented in `src/lifecycle/v_shield.rs`, the V-Shield provides:
- **Environment Sanitization**: Surgical removal of "Dangerous Toxins" (untrusted environment variables) to prevent inheritance by child processes.
- **Socket Hygiene**: Secure management of Unix Domain Sockets and abstract namespace sockets (Linux).
- **FD Purge**: Ensures no file descriptors are leaked to forked workers.

### Iron Zygote
The Zygote process is the "parent" of all Python workers in Velo. It provides:
- **Pre-initialization**: Pre-loads the Python interpreter and common libraries (via RFC-0035 Native Preload).
- **Fast Forking**: Uses `fork()` to spawn workers in milliseconds, avoiding Python cold-start costs.
- **Permission Boundary**: The Zygote is designed to run with restricted permissions, providing a security layer between the host and the user's Python code.

## Security Boundaries

### Zygote Permissions
- **Isolation**: Zygote processes are isolated from the host filesystem where possible.
- **Provenance Guard**: Validates that all library paths loaded into the Zygote are within trusted prefixes defined in `constants.toml`.
- **Environment Shield**: Only explicitly whitelisted environment variables are propagated to workers.

## Usage

This crate is primarily used as a dependency for `velo-serve` and `velo-cli`. It is not intended for standalone execution.
