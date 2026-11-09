# Changelog

## v2 — awaiting publication

### Fixed

- Revised Snakemake `ancient()` markers so downloaded trend rasters are
  treated consistently as stable inputs, while coverage analysis becomes
  a normal dependency for the coverage/terrain complexity figure.
- Fixed sign conventions in Tables 2 and 3.
- Fixed treating "Region number" as numeric scale during plotting which
  led to defaulting to a less explicit palette and not mentioning all
  regions in the legend.
- Revised the paper template, fixing multiple issues.

### Updated

- Renumbered retained figures to 1–8 and A1–A4, including scripts and workflow paths.
- Removed dropped figures and unused manuscript-only analysis paths.
- Updated to CryoSwath 0.2.10 to repair ESA track download.
- Load MAAP and Earthdata credentials from an ignored private file with environment overrides.
- Keep secrets out of serialized job configuration and cookie-helper command arguments.
- Recognize MAAP authentication alongside Science Server FTP credentials.
- Verify TLS certificates in the cookie helper and preserve existing wget CA/proxy settings.

## v1 - 2026-06-02

### Added

- Published the first tagged release of the CryoSwath paper reproduction
  workflow.
