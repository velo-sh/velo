# Granian Vendor Information

## Source Repository
- **Origin**: https://github.com/emmett-framework/granian
- **Version**: 2.6.1
- **Commit**: `0fbc4b9b09f2f953b49f1fb57d110d24b855bd1d`
- **Date**: 2026-01-07 11:12:43 +0100
- **Vendored**: 2026-01-12

## License
BSD-3-Clause (see LICENSE file)

## Modifications from Upstream
1. Changed crate-type from `cdylib` to `rlib`
2. Renamed package from `granian` to `granian-core`
3. Removed allocator globals (jemalloc/mimalloc) - use Velo's

## How to Update

```bash
# 1. Clone new version
git clone --depth 1 https://github.com/emmett-framework/granian.git /tmp/granian-new

# 2. Record commit hash
cd /tmp/granian-new && git log -1 --format="%H %ci"

# 3. Replace source
rm -rf vendor/granian/src
cp -r /tmp/granian-new/src vendor/granian/

# 4. Update this file with new commit info

# 5. Test compilation
cargo check
```

## Integration with Velo
This vendored code is used by `src/rsgi/` for RFC-0019 Native Sovereignty.
Granian provides the ASGI/RSGI state machines and zero-copy conversion.
