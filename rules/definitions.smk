from pathlib import Path
import re
from cryoswath_paper_workflow.workflow_support import (
    make_o2reg_filename_token_list,
    o1o2reg_tuple_list,
    rgi_names,
    strip_spec_chars,
)
import yaml

config.update(config.get("_source_overrides", {}))


def resolve_calval_source(config):
    source = (config.get("calval_source") or "").strip().lower()
    if source not in {"downloaded", "produced"}:
        raise ValueError("calval_source must be one of downloaded or produced")
    return source


def resolve_coverage_analysis_source(config):
    source = (config.get("coverage_analysis_source") or "").strip().lower()
    if source not in {"downloaded", "produced"}:
        raise ValueError(
            "coverage_analysis_source must be one of downloaded or produced"
        )
    return source


def resolve_glacierized_area_source(config):
    source = (config.get("glacierized_area_source") or "").strip().lower()
    if source not in {"downloaded", "produced"}:
        raise ValueError("glacierized_area_source must be one of downloaded or produced")
    return source


def resolve_elevation_timeseries_source(config):
    source = (config.get("elevation_timeseries_source") or "").strip().lower()
    if source not in {"downloaded", "produced"}:
        raise ValueError(
            "elevation_timeseries_source must be one of downloaded or produced"
        )
    return source


def resolve_publication_artifact_source(config):
    source = (config.get("publication_artifact_source") or "").strip().lower()
    if source not in {"downloaded", "produced"}:
        raise ValueError(
            "publication_artifact_source must be one of downloaded or produced"
        )
    return source


CALVAL_SOURCE = resolve_calval_source(config)
COVERAGE_ANALYSIS_SOURCE = resolve_coverage_analysis_source(config)
GLACIERIZED_AREA_SOURCE = resolve_glacierized_area_source(config)
ELEVATION_TIMESERIES_SOURCE = resolve_elevation_timeseries_source(config)
PUBLICATION_ARTIFACT_SOURCE = resolve_publication_artifact_source(config)

# Anchor repo-sensitive paths on this included file.
DEFINITIONS_DIR = Path(str(workflow.current_basedir)).resolve()
REPO_ROOT = DEFINITIONS_DIR.parent


def repo_path(*parts):
    return str(REPO_ROOT.joinpath(*parts))


def env_path(name):
    return repo_path("envs", name)


def script_path(name):
    return repo_path("scripts", name)


def notebook_path(name):
    return repo_path("notebooks", name)


def pathvar_path(path):
    return workflow.pathvars.apply(path)


RGI_O1_REGIONS = "<resources>/auxiliary/RGI/RGI2000-v7.0-o1regions.feather"
RGI_O2_REGIONS = "<resources>/auxiliary/RGI/RGI2000-v7.0-o2regions.feather"
CRYOSWATH_AUX_FILES = [
    *expand(
        "<resources>/auxiliary/CryoSat-2_SARIn_{suffix}",
        suffix=["ground_tracks.feather", "file_names.pkl"],
    ),
    RGI_O1_REGIONS,
    RGI_O2_REGIONS,
]

MANUSCRIPT_EXTERNAL_FIGURE_MANIFEST = "paper/external_figures.txt"
TREND_DATASET_ARCHIVE_URL = (
    "https://data.4tu.nl/ndownloader/items/85738a14-6652-4e0c-8552-d6fc729141b3/versions/3"
)
PUBLICATION_DATA_URL = (
    "https://data.4tu.nl/file/48892e44-ec2a-434f-bac1-8b7e1507e7d2/df7d357e-f828-4cb5-acb3-dd3a4364530e"
)
AVERAGE_ELEVATION_FILENAME = (
    "Arctic_monthly_avg_glacier_surface_elevation_wrt_2010_per_RGI_o2region__meter.csv"
)
AREA_FILENAME = "o2region__area_km2.csv"
COPERNICUS_LATEX_TEMPLATE_URL = "https://publications.copernicus.org/Copernicus_LaTeX_Package.zip"
RGI_URL = "https://daacdata.apps.nsidc.org/pub/DATASETS/nsidc0770_rgi_v7"
RGI_REGIONAL_URL = f"{RGI_URL}/regional_files"
RGI_GLOBAL_ATTRS_URL = f"{RGI_URL}/global_files/attributes"


def local_trend_path(token, period="2010-2024"):
    return f"<resources>/trends_dataset/Glacier_surface_elevation_trend_{period}__{token}__500x500m.tif"


def calval_compare_path(kind, token):
    return f"<resources>/calval/compare_arcticdem_strips__{kind}__{token}.csv"


def read_manifest_list(path):
    manifest_path = Path(path)
    if manifest_path.suffix in {".yml", ".yaml"}:
        data = yaml.safe_load(manifest_path.read_text())
        if isinstance(data, dict):
            if "items" in data:
                return list(data["items"])
            if "external_figures" in data:
                return list(data["external_figures"])
        return list(data or [])
    return [
        line.strip()
        for line in manifest_path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def download_archive_members(url, archive_path, destinations, log_path):
    import hashlib
    import shutil
    import urllib.request
    import zipfile

    archive_path = Path(archive_path)
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")

    def log_message(message):
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")

    destination_paths = [Path(path) for path in destinations]
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if not url:
        raise ValueError(
            "No publication data archive URL is configured. Set "
            "publication_data_url in config/snakemake.yaml or pass "
            "--config publication_data_url=<4TU download URL>."
        )
    log_message(f"Downloading archive from {url}")
    urllib.request.urlretrieve(url, archive_path)

    def archive_basename_candidates(destination_path):
        basename = destination_path.name
        candidates = []
        try:
            candidates.append(destination_path.relative_to(REPO_ROOT).as_posix())
        except ValueError:
            candidates.append(destination_path.as_posix())
        candidates.append(basename)
        if basename.startswith("compare_arcticdem_strips__"):
            candidates.append(f"calval__{basename}")
        return candidates

    checksum_members = {
        "SHA256SUMS",
        "SHA256SUMS.txt",
        "checksums.sha256",
        "publication_data_manifest.sha256",
    }
    expected_sha256_by_member = {}

    destination_by_candidate = {
        candidate: path
        for path in destination_paths
        for candidate in archive_basename_candidates(path)
    }
    members_by_destination = {}
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            basename = Path(info.filename).name
            if basename not in checksum_members:
                continue
            for raw_line in archive.read(info.filename).decode("utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(maxsplit=1)
                if len(parts) != 2:
                    continue
                checksum, member_name = parts
                member_name = member_name.lstrip("*").strip()
                expected_sha256_by_member[member_name] = checksum.lower()

        for info in archive.infolist():
            if Path(info.filename).name in checksum_members:
                continue
            basename = Path(info.filename).name
            member_candidates = [info.filename, basename]
            destination_path = next(
                (
                    destination_by_candidate[candidate]
                    for candidate in member_candidates
                    if candidate in destination_by_candidate
                ),
                None,
            )
            if destination_path and destination_path not in members_by_destination:
                members_by_destination[destination_path] = info.filename

        missing = [
            path.name
            for path in destination_paths
            if path not in members_by_destination
        ]
        if missing:
            raise FileNotFoundError(
                "archive is missing required files:\n" + "\n".join(sorted(missing))
            )

        for destination_path in destination_paths:
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            archive_member = members_by_destination[destination_path]
            log_message(f"Extracting {archive_member} -> {destination_path}")
            with (
                archive.open(archive_member) as src_handle,
                destination_path.open("wb") as dst_handle,
            ):
                shutil.copyfileobj(src_handle, dst_handle)

        validated = 0
        for destination_path, archive_member in members_by_destination.items():
            checksum = expected_sha256_by_member.get(archive_member)
            if checksum is None:
                try:
                    rel_member = destination_path.relative_to(REPO_ROOT).as_posix()
                except ValueError:
                    rel_member = destination_path.as_posix()
                checksum = expected_sha256_by_member.get(rel_member)
            if checksum is None:
                continue
            actual = hashlib.sha256(destination_path.read_bytes()).hexdigest()
            if actual != checksum:
                raise ValueError(
                    f"checksum mismatch for {destination_path}: "
                    f"expected {checksum}, got {actual}"
                )
            validated += 1
        if expected_sha256_by_member:
            log_message(f"Validated {validated} extracted files against checksums")

    archive_path.unlink(missing_ok=True)


filename_tokens = [
    "__".join(
        list(
            map(
                lambda x: strip_spec_chars(rgi_names[x[0]][x[1]]),
                [(o1, "name"), (o1, o2)],
            )
        )
    )
    for o1, o2_list in o1o2reg_tuple_list
    for o2 in o2_list
]

rgi_shapefile_tokens = [
    rgi_names[o1]["long_code"]
    for o1, _ in o1o2reg_tuple_list
]

TREND_RASTERS = [local_trend_path(token) for token in filename_tokens]
TREND_DATASET_LOCAL_DIR = config.get("trend_dataset_local_dir")
if TREND_DATASET_LOCAL_DIR:
    TREND_DATASET_LOCAL_DIR = (REPO_ROOT / TREND_DATASET_LOCAL_DIR).resolve()
    if TREND_DATASET_LOCAL_DIR == Path(pathvar_path("<resources>/trends_dataset")).resolve():
        raise ValueError("trend_dataset_local_dir must differ from the output directory")
CURRENT_SOURCE_AREA_TABLE = f"<resources>/{AREA_FILENAME}"
CURRENT_SOURCE_AVG_TABLE = f"<resources>/{AVERAGE_ELEVATION_FILENAME}"
TREND_DATASET_OUTPUTS = [
    *TREND_RASTERS,
]
CURRENT_SOURCE_CALVAL_INTERPOLATION = [
    calval_compare_path("interpolation_type", token)
    for token in rgi_shapefile_tokens
]
CURRENT_SOURCE_CALVAL_TEMPORAL = [
    calval_compare_path("temporal_correlation", token)
    for token in rgi_shapefile_tokens
]
CURRENT_SOURCE_COVERAGE_ANALYSIS = "<results>/coverage_analysis.csv"

MANUSCRIPT_GENERATED_FIGURES = [
    "paper/figures/fig02__example__wf_start.pdf",
    "paper/figures/fig03__geometry_sketch.png",
    "paper/figures/fig04__arctic-wide_time_series.pdf",
    "paper/figures/fig05__regional_time_series.pdf",
    "paper/figures/fig15__vatna_hugonnet_stat_comparison.pdf",
    "paper/figures/fig16__coverage_terraincomplexity_correlation.pdf",
    "paper/figures/figA1__bias_by_interp_type.pdf",
    "paper/figures/figA2__one_year_error_correlation.pdf",
    "paper/figures/figA3__vavilov_feature.pdf",
]

MANUSCRIPT_EXTERNAL_FIGURES = read_manifest_list(MANUSCRIPT_EXTERNAL_FIGURE_MANIFEST)

PUBLICATION_ARCHIVED_FIGURES = [
    "paper/figures/fig02__example__wf_start.pdf",
    "paper/figures/fig15__vatna_hugonnet_stat_comparison.pdf",
    "paper/figures/figA3__vavilov_feature.pdf",
]

PUBLICATION_ARCHIVED_MANUSCRIPT_INPUTS = [
    "<results>/closeup__icecap__barnes.yaml",
    "<results>/closeup__icecap__penny.yaml",
    "<results>/closeup__icecap__sukkerqara.yaml",
    "<results>/closeup__icecap__scandinavian.yaml",
    "<results>/omitted_subregions.csv",
    "<results>/result__greenland_trends.csv",
    "<results>/result__regional_trends.csv",
    "<results>/result__period_comparison_p_values.csv",
    "<results>/result__value_collection.yaml",
    "<results>/tab01__subregion_trend_table.tex",
    "<results>/tabA2__subregion_overview.tex",
    "<results>/vatna_deviation_analysis.csv",
    "<results>/vatna_deviation_analysis.yaml",
]

PUBLICATION_ARCHIVED_OUTPUTS = [
    *PUBLICATION_ARCHIVED_FIGURES,
    *PUBLICATION_ARCHIVED_MANUSCRIPT_INPUTS,
]

PUBLICATION_RERUNNABLE_FIGURES = [
    "paper/figures/fig04__arctic-wide_time_series.pdf",
    "paper/figures/fig03__geometry_sketch.png",
    "paper/figures/fig05__regional_time_series.pdf",
    "paper/figures/fig16__coverage_terraincomplexity_correlation.pdf",
    "paper/figures/figA1__bias_by_interp_type.pdf",
    "paper/figures/figA2__one_year_error_correlation.pdf",
]

PUBLICATION_REPRODUCTION_OUTPUTS = [
    "paper/manuscript.tex",
    *PUBLICATION_RERUNNABLE_FIGURES,
    *PUBLICATION_ARCHIVED_FIGURES,
    *MANUSCRIPT_EXTERNAL_FIGURES,
]
