# mvp-ship-gate

Blocking MVP delivery gate for GitHub Actions. Catches dead links, empty handlers, placeholders, missing README/Terms, missing privacy when forms exist, and baseline SEO chrome.

This is **not** a WCAG 2.2 AA certificate.

## Use in a product repo

```yaml
# .github/workflows/mvp-ship-gate.yml
name: mvp-ship-gate
on:
  pull_request:
  push:
    branches: [main]
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: SuperfastSimon/mvp-ship-gate@main
        with:
          root: .
          mode: light   # light on PRs, full on main
          format: github
```

Copy `examples/consumer.yml` if you want the mode switch (PR = light, main/tag = full).

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `root` | `.` | Project root |
| `mode` | `full` | `light` or `full` |
| `format` | `github` | `text` / `json` / `github` / `junit` |
| `report-path` | `artifacts/mvp-ship-gate.json` | JSON report |
| `upload-artifact` | `true` | Upload report on PASS and FAIL |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | PASS |
| 1 | Product checks failed — block promote |
| 2 | Harness/infra error — also block, not a product PASS |

Mark this workflow as a **required status check** on the default branch. Do not set `continue-on-error` on the gate step.
