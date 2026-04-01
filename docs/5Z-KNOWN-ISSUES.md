# Known Issues

> Known issues and workarounds.

| Issue | Workaround | Status |
|-------|-----------|--------|
| State.json race condition with concurrent marker runs | Fixed with atomic read-modify-write | **Resolved** |
| Metric extraction fails with bare regex instead of shell command | Use full shell command in `metric.extract` | **Resolved** |
