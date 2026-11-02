# Changelog

## Unreleased

### Updated

- Renumbered retained figures to 1–8 and A1–A4, including scripts and workflow paths.
- Removed dropped figures and unused manuscript-only analysis paths.
- Restricted the publication-data archive to explicit required members, with
  membership and checksum verification before replacing the archive.
- Enabled local archive URL overrides and external-figure downloads in both
  reproduction modes.

### Fixed

- Revised Snakemake `ancient()` markers so downloaded trend rasters are
  treated consistently as stable inputs, while coverage analysis becomes
  a normal dependency for the coverage/terrain complexity figure.
- Fixed sign conventions in Tables 2 and 3.
- Fixed treating "Region number" as numeric scale during plotting which
  let to defaulting to a less explicit palette and not mentioning all
  regions in the legend.
- Revise paper template, fixing multiple issues.

## v1 - 2026-06-02

### Added

- Published the first tagged release of the CryoSwath paper reproduction
  workflow.
