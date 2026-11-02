#!/usr/bin/env python3
"""Build the 4TU publication-data archive for the manuscript workflow."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "resources" / "downloads" / "publication_data_candidate.zip"


RGI_TOKENS = [
    "01_alaska",
    "03_arctic_canada_north",
    "04_arctic_canada_south",
    "05_greenland_periphery",
    "06_iceland",
    "07_svalbard_jan_mayen",
    "08_scandinavia",
    "09_russian_arctic",
]

GENERATED_MANUSCRIPT_FIGURES = [
    "paper/figures/fig01__example__wf_start.pdf",
    "paper/figures/fig02__geometry_sketch.png",
    "paper/figures/fig03__arctic-wide_time_series.pdf",
    "paper/figures/fig04__regional_time_series.pdf",
    "paper/figures/fig07__vatna_hugonnet_stat_comparison.pdf",
    "paper/figures/fig08__coverage_terraincomplexity_correlation.pdf",
    "paper/figures/figA2__bias_by_interp_type.pdf",
    "paper/figures/figA3__one_year_error_correlation.pdf",
]

EXTERNAL_MANUSCRIPT_FIGURES = [
    line.strip()
    for line in (PROJECT_ROOT / "paper" / "external_figures.txt").read_text().splitlines()
    if line.strip() and not line.strip().startswith("#")
]


def file_spec(path: str, category: str, role: str) -> dict[str, str]:
    return {"path": path, "category": category, "role": role}


def publication_members() -> list[dict[str, str]]:
    specs = [
        file_spec(
            "resources/o2region__area_km2.csv",
            "downloaded_analysis_input",
            "Glacierized area by RGI order-2 region for time-series weighting.",
        ),
        file_spec(
            "resources/Arctic_monthly_avg_glacier_surface_elevation_wrt_2010_per_RGI_o2region__meter.csv",
            "downloaded_analysis_input",
            "Monthly regional elevation time series used by the time-series figures.",
        ),
        file_spec(
            "results/coverage_analysis.csv",
            "downloaded_analysis_input",
            "Terrain-complexity coverage analysis input for figure 8.",
        ),
    ]

    for token in RGI_TOKENS:
        specs.append(
            file_spec(
                f"resources/calval/select_arcticdem_strips__{token}.lock.feather",
                "downloaded_analysis_input",
                f"Random point selection for cal/val comparison in {token}.",
            )
        )

    for kind in ("interpolation_type", "temporal_correlation"):
        for token in RGI_TOKENS:
            specs.append(
                file_spec(
                    f"resources/calval/compare_arcticdem_strips__{kind}__{token}.csv",
                    "downloaded_analysis_input",
                    f"Derived cal/val comparison table for {kind} in {token}.",
                )
            )

    specs.extend(
        [
            file_spec(
                "results/closeup__icecap__scandinavian.yaml",
                "manuscript_input",
                "Derived Scandinavian closeup values for manuscript text.",
            ),
            file_spec(
                "results/coverage_terraincomplexity_correlation.yaml",
                "manuscript_input",
                "Regression coefficients derived from the coverage analysis.",
            ),
            file_spec(
                "results/omitted_subregions.csv",
                "manuscript_input",
                "List and area share of omitted RGI subregions.",
            ),
            file_spec(
                "results/one_year_error_correlation.txt",
                "manuscript_input",
                "One-year temporal error correlation used by the manuscript.",
            ),
            file_spec(
                "results/result__regional_trends.csv",
                "manuscript_input",
                "Derived Arctic regional trend values used by manuscript tables.",
            ),
            file_spec(
                "results/result__value_collection.yaml",
                "manuscript_input",
                "Derived scalar values injected into the manuscript template.",
            ),
            file_spec(
                "results/result__period_comparison_p_values.csv",
                "manuscript_input",
                "Regional and Arctic-wide p-values comparing 2010-2014 with 2020-2024 trends.",
            ),
            file_spec(
                "results/tab01__subregion_trend_table.tex",
                "manuscript_input",
                "Rendered LaTeX trend table for the manuscript.",
            ),
            file_spec(
                "results/tab03__JG_comparison.tex",
                "manuscript_input",
                "Rendered LaTeX comparison table for the manuscript.",
            ),
            file_spec(
                "results/tabA2__subregion_overview.tex",
                "manuscript_input",
                "Rendered LaTeX supplementary subregion overview table.",
            ),
            file_spec(
                "results/uncertainty_by_interp__correlations.csv",
                "manuscript_input",
                "Derived cal/val interpolation uncertainty correlation table.",
            ),
            file_spec(
                "results/uncertainty_by_interp__uncertainty.csv",
                "manuscript_input",
                "Derived cal/val interpolation uncertainty summary table.",
            ),
            file_spec(
                "results/vatna_deviation_analysis.csv",
                "manuscript_input",
                "Derived Vatnajokull reference-comparison table.",
            ),
            file_spec(
                "results/vatna_deviation_analysis.yaml",
                "manuscript_input",
                "Derived Vatnajokull reference-comparison scalar values.",
            ),
        ]
    )

    for figure_path in GENERATED_MANUSCRIPT_FIGURES + EXTERNAL_MANUSCRIPT_FIGURES:
        specs.append(
            file_spec(
                figure_path,
                "manuscript_figure",
                "Retained manuscript figure or geometry panel required for reproduction.",
            )
        )

    return specs


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def format_tree(paths: list[str]) -> str:
    tree: dict[str, dict[str, object] | None] = {}
    for path in sorted(paths):
        node = tree
        parts = path.split("/")
        for part in parts[:-1]:
            child = node.get(part)
            if child is None:
                child = {}
                node[part] = child
            node = child  # type: ignore[assignment]
        node[parts[-1]] = None

    def render(node: dict[str, dict[str, object] | None], prefix: str = "") -> list[str]:
        lines: list[str] = []
        entries = sorted(node.items(), key=lambda item: item[0])
        for index, (name, child) in enumerate(entries):
            is_last = index == len(entries) - 1
            branch = "└── " if is_last else "├── "
            lines.append(f"{prefix}{branch}{name}")
            if child is not None:
                extension = "    " if is_last else "│   "
                lines.extend(render(child, prefix + extension))
        return lines

    return ".\n" + "\n".join(render(tree))


def dataset_readme(archive_paths: list[str], *, draft: bool = False) -> str:
    tree = format_tree(archive_paths)
    status = "DRAFT — not for release or publication use" if draft else "Candidate — pending publication"
    return f"""README
======

Status: {status}.

Dataset title:
    **Ancilliary data for the reproduction workflow of the article "CryoSwath: a CryoSat-2 swath processor and monthly surface elevation dataset for Arctic mountain glaciers"**

Structure:

{tree}

License: CC-BY-4.0

Contact: <jan.haacker@boku.ac.at>

Summary
-------

The data accompany an automated workflow that reproduces the associated
manuscript "CryoSwath: a CryoSat-2 swath processor and monthly surface
elevation dataset for Arctic mountain glaciers". The data are not
required but allow skipping computationally expensive processes or
verifying that reproduced results are consistent with the published
manuscript. The data are structured in accordance with the workflow:
`./resources` contains lower-level intermediate data, `./results` are
directly used to assemble the latex document, and `./paper/figures`
contain retained rendered figures and the source panels needed to assemble
the geometry figure. Membership is explicit; unrelated local files are excluded.

Contents
--------

- `resources/o2region__area_km2.csv`: derived glacierized-area table.
- `resources/Arctic_monthly_avg_glacier_surface_elevation_wrt_2010_per_RGI_o2region__meter.csv`: derived regional elevation time series.
- `resources/calval/compare_arcticdem_strips__*.csv`: derived cal/val summary tables.
- `results/*`: derived manuscript tables, scalar values, and figure inputs.
- `paper/figures/*`: rendered manuscript figure artifacts.

Ancilliary:

- `CHANGELOG.md`: candidate change record.
- `publication_data_manifest.json`: machine-readable inventory.
- `SHA256SUMS`: checksums for archive members.
- `LICENSE.txt`: dataset license notice.

Method
------

This candidate accompanies the retained-paper Snakemake (Python) workflow.
It is pending publication; no download URL, DOI, or release version is assigned
here. Use an explicitly configured local candidate for validation. Draft
archives built with `--allow-missing` are validation artifacts and must not be
used for a release or publication reproduction.

`publication_data_manifest.json` lists every required data/figure member, any
missing members, and the size and SHA-256 digest of each packaged data/figure
file. `SHA256SUMS` covers every member except itself, including the manifest.
The builder verifies exact membership, sizes, and checksums before replacing
the candidate archive.

License
-------

Packaged files are distributed under the Creative Commons Attribution
4.0 International license (CC-BY-4.0). Consider citing the accompanied
article instead or next to the current dataset if you refer to figures
or values that are part of the article.
"""


def license_text() -> str:
    return """Creative Commons Attribution 4.0 International (CC-BY-4.0)

The derived data files and rendered figure artifacts in this archive are made
available under the Creative Commons Attribution 4.0 International license.

You are free to share and adapt the material for any purpose, including
commercially, provided that appropriate credit is given, a link to the license
is provided, and changes are indicated.

License text: https://creativecommons.org/licenses/by/4.0/legalcode
Human-readable summary: https://creativecommons.org/licenses/by/4.0/

This license notice applies to the packaged derived publication data and
rendered manuscript artifacts. It does not relicense upstream raw or protected
datasets used to derive them.
"""


def changelog_text() -> str:
    return """\
# CHANGELOG

## Candidate — pending publication

- Restricted membership to retained manuscript figures, geometry source panels,
  and their explicit reproduction inputs.
- Renumbered retained figures and removed Vavilov and dropped regional maps.
- Removed unused Barnes, Penny, Sukkertoppen, and Greenland manuscript inputs.
- Added complete membership and checksum verification.
- Archives built with `--allow-missing` are drafts, never release artifacts.
"""


def build_archive(output: Path, allow_missing: bool) -> int:
    output = output.resolve()
    original = PROJECT_ROOT / "resources" / "downloads" / "publication_data.zip"
    if output == original.resolve() or (
        output.exists() and original.exists() and output.samefile(original)
    ):
        print("Refusing to overwrite the original publication_data.zip", file=sys.stderr)
        return 1

    specs = publication_members()
    missing = [
        spec["path"]
        for spec in specs
        if not (PROJECT_ROOT / spec["path"]).is_file()
    ]
    if missing and not allow_missing:
        print("Missing required publication-data members:", file=sys.stderr)
        for path in missing:
            print(f"  - {path}", file=sys.stderr)
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)

    manifest_entries = []
    checksum_lines: list[str] = []
    existing_specs = [
        spec for spec in specs if (PROJECT_ROOT / spec["path"]).is_file()
    ]
    seen_paths = set()
    duplicate_paths = []
    for spec in specs:
        if spec["path"] in seen_paths:
            duplicate_paths.append(spec["path"])
        seen_paths.add(spec["path"])
    if duplicate_paths:
        print("Duplicate publication-data members:", file=sys.stderr)
        for path in duplicate_paths:
            print(f"  - {path}", file=sys.stderr)
        return 1

    for spec in existing_specs:
        path = PROJECT_ROOT / spec["path"]
        checksum = sha256_file(path)
        manifest_entries.append(
            {
                "path": spec["path"],
                "category": spec["category"],
                "role": spec["role"],
                "size_bytes": path.stat().st_size,
                "sha256": checksum,
            }
        )
        checksum_lines.append(f"{checksum}  {spec['path']}")

    archive_paths = sorted(
        [spec["path"] for spec in existing_specs]
        + ["LICENSE.txt", "README.md", "CHANGELOG.md", "publication_data_manifest.json", "SHA256SUMS"]
    )
    docs = {
        "README.md": dataset_readme(archive_paths, draft=allow_missing).encode("utf-8"),
        "LICENSE.txt": license_text().encode("utf-8"),
        "CHANGELOG.md": changelog_text().encode("utf-8"),
    }

    manifest = {
        "title": 'Ancilliary data for the reproduction workflow of the article "CryoSwath: a CryoSat-2 swath processor and monthly surface elevation dataset for Arctic mountain glaciers"',
        "article_title": "CryoSwath: a CryoSat-2 swath processor and monthly surface elevation dataset for Arctic mountain glaciers",
        "publication_status": "draft" if allow_missing else "candidate_pending_publication",
        "dataset_doi": None,
        "code_release_doi": None,
        "release_version": None,
        "license": "CC-BY-4.0",
        "created_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "generated_by": "tools/create_publication_data_archive.py",
        "archive_name": output.name,
        "required_members": sorted(spec["path"] for spec in specs),
        "missing_members": missing,
        "files": manifest_entries,
    }
    docs["publication_data_manifest.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    for arcname, data in docs.items():
        checksum_lines.append(f"{sha256_bytes(data)}  {arcname}")

    docs["SHA256SUMS"] = ("\n".join(sorted(checksum_lines)) + "\n").encode("utf-8")

    with tempfile.NamedTemporaryFile(
        dir=output.parent, prefix=f".{output.name}.", suffix=".tmp", delete=False
    ) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for spec in sorted(existing_specs, key=lambda item: item["path"]):
                archive.write(PROJECT_ROOT / spec["path"], spec["path"])
            for arcname in sorted(docs):
                archive.writestr(arcname, docs[arcname])

        with zipfile.ZipFile(temporary) as archive:
            if sorted(archive.namelist()) != archive_paths:
                raise ValueError("Archive membership does not match the explicit inventory")
            expected = {
                entry["path"]: (entry["size_bytes"], entry["sha256"])
                for entry in manifest_entries
            }
            expected.update(
                (name, (len(data), sha256_bytes(data))) for name, data in docs.items()
            )
            for name, (size, checksum) in expected.items():
                with archive.open(name) as member:
                    actual = hashlib.file_digest(member, "sha256").hexdigest()
                if archive.getinfo(name).file_size != size or actual != checksum:
                    raise ValueError(f"Archive size/checksum mismatch for {name}")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)

    print(f"Wrote {'DRAFT (not for release)' if allow_missing else 'candidate (pending publication)'}: {output}")
    print(f"Packaged {len(existing_specs)} data/figure files and {len(docs)} docs")
    if missing:
        print(f"Skipped {len(missing)} missing members because --allow-missing was set")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create the path-preserving publication-data zip archive."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Archive path to write (default: {DEFAULT_OUTPUT.relative_to(PROJECT_ROOT)})",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Create a draft archive even when required members are missing.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return build_archive(args.output, args.allow_missing)


if __name__ == "__main__":
    raise SystemExit(main())
