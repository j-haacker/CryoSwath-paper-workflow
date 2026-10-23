# CryoSwath paper workflow

This repository contains the Snakemake workflow that builds the figures,
tables, and results for the manuscript [*CryoSwath: a CryoSat-2 swath
processor and monthly surface elevation dataset for Arctic mountain
glaciers*](https://doi.org/{TODO:replace}). Obtain the immutable code
release from DOI
[10.4121/fdad7bbe-0deb-43d4-9a41-237be0d60df6.v2](https://doi.org/10.4121/fdad7bbe-0deb-43d4-9a41-237be0d60df6.v2).
Running the full workflow requires (free) registration at NSIDC and ESA
services and substantial computational resources. Therefore, the
workflow supports using preprocessed resources instead of running tasks
that require authentication or extensive resources.

## Adjustable reproduction depth

The current workflow supports reproducing the results of the associated
manuscript using published datasets as input. It uses source selectors
to choose how far upstream each analysis is reproduced: `downloaded`
uses archived intermediate or final outputs, while `produced`
regenerates the selected outputs from their workflow inputs.

[![Selector-aware Snakemake rule graph showing the produced rules bypassed by each downloaded source selector](docs/workflow-source-selectors.svg)](docs/workflow-source-selectors.svg)

The diagram is the union of the `publication_reproduction` rule graphs for the
produced and downloaded selector variants. A colored cluster is omitted when
its matching selector is set to `downloaded`; colored dashed edges show where
the corresponding archived outputs re-enter the workflow.

| Tier | How to run | Intended use |
| --- | --- | --- |
| Fast reproduction | `pixi run reproduce 1` | Download the public reproduction archive, rerun lightweight figure paths, and materialize `paper/manuscript.tex` without Earthdata or ESA credentials. |
| Selective produced paths | `pixi run snakemake <target> --cores <n> --config <selector>=produced` | Rebuild one analysis path from inputs without expanding the whole workflow. Some produced paths are public and workstation-friendly; others need credentials or large memory. |

Instead of passing `--config` arguments, edit `config/snakemake.yaml` to
persist source-selector settings. With all selectors set to `produced`,
the full workflow took between 1.5 and 5 hours using 48 cores on an AMD
EPYC 7452 CPU (up to 2.35 GHz) for test runs skipping ArcticDEM mosaic
and strip downloads. Peak observed per-job memory was about 50 GB;
earlier up to 90 GB were observed for heavier cal/val runs. Add
`--resources mem_mb=16000` to enforce a memory limit of about 16 GB for
example but expect the runtime to increase.

## Requirements and platforms

The primary tested route is x86_64 Linux. On Windows, use WSL2. Please
install `pixi`:

```bash
curl -fsSL https://pixi.sh/install.sh | sh
```

or, from an existing conda installation:

```bash
conda install conda-forge::pixi
```

See the Pixi installation docs at <https://pixi.prefix.dev/latest/installation/>
and the conda-forge package at <https://anaconda.org/conda-forge/pixi>.

While pixi is recommended, you can attempt to use the Linux-only explicit conda
environment at `envs/default.linux-64.pin.txt` instead.

Pixi environments are also locked for Intel and Apple Silicon macOS. They are
untested; use them at your own risk. Native Windows is not supported because
the workflow invokes POSIX shell tools. Results can differ on insignificant
digits; use the provided random-strip lock files
(`resources/calval/select_arcticdem_strips__*.lock.feather`) when relevant.

## Quickstart

Download and unpack the code release above, then run the following from the
repository root. The final argument is the number of cores Snakemake may use.
Further snakemake arguments can be appended.

```bash
pixi run dry-run 1
pixi run reproduce 1
```

The first command shows the planned work without changing outputs. The second
downloads the public reproduction archive, validates its checksums,
reruns the lightweight figure paths, and requires neither Earthdata
nor ESA credentials. Produced source selectors below document which opt-in
paths need credentials or large local resources. A successful run produces
`paper/manuscript.tex` and the following figures:

- `paper/figures/fig03__geometry_sketch.png`
- `paper/figures/fig04__arctic-wide_time_series.pdf`
- `paper/figures/fig05__regional_time_series.pdf`
- `paper/figures/fig16__coverage_terraincomplexity_correlation.pdf`
- `paper/figures/figA1__bias_by_interp_type.pdf`
- `paper/figures/figA2__one_year_error_correlation.pdf`

## Credentials

The workflow supports reproducing manuscript contents to a definable
depth. Going beyond the above, the workflow downloads some protected
input data. Configure the relevant credentials before running targets
that need those downloads. The registration at the concerned services is
free; however, you can skip the processing steps that involve the
credentials by selecting `downloaded` (as opposed to `produced`) for the
concerned processing steps. The quickstart above uses the
default downloaded sources and does not need these credentials.

### NSIDC/RGI Earthdata

RGI shapefile downloads use NASA Earthdata credentials. The workflow resolves
them in this order:

1. `earthdata_username` and `earthdata_password` in `config/snakemake.yaml`
2. `EARTHDATA_USERNAME` and `EARTHDATA_PASSWORD`
3. `$HOME/.netrc`
4. `./.netrc`
5. `./.nsidc_cookies`

The config-file fields are present but empty by default:

```yaml
earthdata_username: ""
earthdata_password: ""
```

### ESA CryoSat-2 L1b

ESA CryoSat-2 L1b downloads, including
`fig02__coherence_waveform_examples`, use ESA EOIAM credentials. Environment
variables are the recommended setup:

```bash
export EOIAM_USER="your-esa-username"
export EOIAM_PASSWORD="your-esa-password"
```

The ESA lookup order is `EOIAM_USER`/`EOIAM_PASSWORD`, keyring,
`$HOME/.netrc` with `machine science-pds.cryosat.esa.int`, and legacy
`config.ini` `[user]` `name`/`password`.

If the needed CryoSat-2 L1b files are already present in
`resources/l1b_cache/`, ESA credentials are not checked. If they are
missing, absent ESA credentials can make downloads fail or appear to
hang while the data access layer retries.

## Configuration

Edit `config/snakemake.yaml` to set configuration parameters, or pass
them on the command line with `--config key=value`. The source selectors
below let you opt into locally produced outputs for one analysis path at a
time. The shipped defaults use downloaded sources. Use
`--config publication_artifact_source=produced` only when you want the PDF
workflow to regenerate artifact-only manuscript inputs and figures from their
upstream dependencies. That path can require credentials and large downloads.

Further, you can opt-out of checking the server certificates
while downloading. This makes you vulnerable to "man-in-the-middle"
attacks and should be avoided; however, in the past it was necessary due
to expired certificates.

## Optional: render the manuscript PDF

The quickstart stops at `paper/manuscript.tex`. To run the workflow's PDF
target, make `pdflatex` available on `PATH`; the workflow downloads the
required Copernicus template files. Pixi does not currently provide a working
portable TeX engine for this manuscript. As a convenience after the quickstart,
Docker can render the generated TeX file:

```shell
docker run --rm \
    -v "$PWD/paper:/work" \
    -w /work \
    -u "$(id -u):$(id -g)" \
    texlive/texlive:latest \
    sh -c 'pdflatex manuscript.tex && pdflatex manuscript.tex'
```

This Docker command is a recommendation and not fully supported/tested.

## Source Selectors

Use one explicit source selector for each analysis that can use either
downloaded outputs or locally produced outputs. In the tables below,
"no auth" means a clean checkout with public internet and no pre-existing
protected-data cache. "Limited resources" means roughly fitting a conservative
workstation, around 16 GB RAM or less, aside from normal local disk and network
needs.

| Produced path | Auth required on clean checkout? | Limited resources? | Notes |
| --- | --- | --- | --- |
| `glacierized_area_source=produced` | No | Yes | Derives `resources/o2region__area_km2.csv` from the public trend rasters. |
| `coverage_analysis_source=produced` | No | Usually | Uses public trend rasters and the public ArcticDEM mosaic. Local benchmarks reached about 10 GB RAM with 24 threads. |
| `elevation_timeseries_source=produced` with `calval_source=downloaded` | No | Usually | Uses public monthly datasets and downloaded cal/val summaries. Expect larger public downloads. |
| `elevation_timeseries_source=produced` with `calval_source=produced` | Yes | No | Inherits the produced cal/val requirements. |
| `calval_source=produced` | Yes | No | Needs RGI/Earthdata inputs in a clean checkout and can reach about 90 GB RAM during strip comparison. |
| `publication_artifact_source=produced` | Yes | No | Rebuilds protected and heavyweight manuscript artifacts; ESA L1b credentials are needed unless required files already exist in `resources/l1b_cache/`. |

Detailed selector reference:

| Config key | Values | What it controls | Auth required on clean checkout? | Resource class |
| --- | --- | --- | --- | --- |
| `calval_source` | `downloaded`, `produced` | Downloaded `resources/calval/compare_arcticdem_strips__*.csv` files vs rebuilding them | `downloaded`: no; `produced`: yes | `downloaded`: light; `produced`: very heavy |
| `coverage_analysis_source` | `downloaded`, `produced` | Downloaded `coverage_analysis.csv` vs rebuilding it | No | `downloaded`: light; `produced`: moderate |
| `glacierized_area_source` | `downloaded`, `produced` | Downloaded `resources/o2region__area_km2.csv` vs deriving it from the published trend rasters | No | Light |
| `elevation_timeseries_source` | `downloaded`, `produced` | Downloaded `resources/Arctic_monthly_avg_glacier_surface_elevation_wrt_2010_per_RGI_o2region__meter.csv` vs deriving it from monthly datasets and cal/val summaries | No if `calval_source=downloaded`; otherwise inherits cal/val | Light to moderate unless produced cal/val is selected |
| `publication_artifact_source` | `downloaded`, `produced` | Archived manuscript inputs/final figures vs rebuilding protected/heavy artifact paths | `downloaded`: no; `produced`: yes | `downloaded`: light; `produced`: heavy |

The published 2010-2024 trend rasters are downloaded by default to
`resources/trends_dataset/`. The area and elevation time-series tables are
active workflow outputs in `resources/` and can be downloaded or reproduced via
their own source selectors.

Downloaded publication inputs are read from the public 4TU publication-data
archive defined by the workflow.

The 2010-2024 trend rasters can be reproduced using the separate 4TU trend
workflow at
`https://data.4tu.nl/v3/datasets/f8c6e417-7893-4c26-a532-296f59712089.git`.

### Local trend-raster input

Use `--config trend_dataset_local_dir=/absolute/path/to/rasters` to supply all
32 trend rasters locally. The directory must differ from the output directory.
Use the same setting on subsequent runs to retain this input source.

If the 4TU monthly-data server has a broken TLS certificate, use
`--config download_verify_tls=false` to skip certificate verification.

## Build One Target From Inputs

To build a different target, run `pixi run snakemake <target> --cores <n>`.
Snakemake builds only that target's dependency closure; setting `calval_source`
or `coverage_analysis_source` to `produced` does not make it build the whole
workflow.

### Examples

No-auth, limited-resource produced examples:

```bash
pixi run snakemake resources/o2region__area_km2.csv --cores 1 --sdm conda --config glacierized_area_source=produced
```

```bash
pixi run snakemake paper/figures/fig16__coverage_terraincomplexity_correlation.pdf --cores 1 --sdm conda --config coverage_analysis_source=produced
```

Rebuild the Arctic-wide time-series figure using a locally reproduced elevation
time-series table and downloaded cal/val summaries:

```bash
pixi run snakemake paper/figures/fig04__arctic-wide_time_series.pdf --cores 1 --sdm conda --config elevation_timeseries_source=produced calval_source=downloaded
```

Advanced produced cal/val example; this is credentialed and can be very
memory-heavy:

```bash
pixi run snakemake results/one_year_error_correlation.txt --cores 1 --sdm conda --config calval_source=produced
```

## Common Target Hints

| Target family | Source selectors that usually matter |
| --- | --- |
| `results/one_year_error_correlation.txt`, `paper/figures/figA1__*.pdf`, `paper/figures/figA2__*.pdf` | `calval_source` |
| `paper/figures/fig04__*.pdf`, `paper/figures/fig05__*.pdf` | `glacierized_area_source`, `elevation_timeseries_source`; `elevation_timeseries_source=produced` also follows `calval_source` |
| `results/tabA2__subregion_overview.tex` | Published trend rasters are downloaded by default |
| `paper/figures/fig16__*.pdf`, `results/coverage_analysis.csv` | `coverage_analysis_source`; published trend rasters are downloaded by default |
| `publication_reproduction` | Default downloaded source selectors plus `publication_artifact_source`; no credentials when the publication archive is configured |
| `paper/manuscript.pdf` | `calval_source`, `coverage_analysis_source`, `glacierized_area_source`, `elevation_timeseries_source`, `publication_artifact_source`; published trend rasters are downloaded by default |

## Resource Usage

Benchmark files are operational diagnostics written under `logs/` and are
ignored by Git. The numbers below are approximate, machine-dependent ranges
from local benchmark runs; use them to choose targets and `--cores`, not as
strict performance guarantees.

| Rule family | Expected resource profile |
| --- | --- |
| Downloaded-source publication path | Mostly light once downloaded inputs are present. The public `publication_reproduction` target reruns tabular-derived figures and materializes `paper/manuscript.tex`; protected/heavy manuscript artifacts are downloaded as final files. |
| Produced-source manuscript path | Summary notebooks generally run in seconds to a few minutes; `result__value_collection` is the main memory-sensitive step and has reached about 25 GB peak RAM locally. |
| Produced cal/val path | Strip selection is moderate, about 0.5-1.5 minutes and under 1 GB RAM per region. Strip comparison is the heavy step, about 2-8 minutes per region and potentially very memory-heavy; local runs have reached about 90 GB RAM. |
| Closeup icecap notebooks | About 0.5-4 minutes per target. These are memory-sensitive, with local runs around 15-50 GB RAM depending on the region. |
| Coverage analysis path | `coverage_analysis` is the critical step, about 1-2 minutes and around 10 GB RAM in local runs with 24 threads. The downstream coverage figure is light. |
| Iceland/reference trend path | Subset, trend, and comparison steps are typically about 0.5-4 minutes and mostly 1-3 GB RAM in this workflow. Full trend-raster production in the separate 4TU workflow is much heavier. |
| Large downloads | ArcticDEM mosaic and remote archives are disk- and network-bound. Benchmark memory usage is not representative of the download size or required free disk space. |
