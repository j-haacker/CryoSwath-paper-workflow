"""Module to produce surface elevation change rates

... from the glacier surface elevation dataset published
with DOI 10.4121/955d7f5a-0e3f-4166-a411-f0dcc4557cb2

Change log:
- v2: Corrects uncertainty scaling.
- v3: Repairs treating Scandinavian subregions collectively (only affects v2).
"""

__version__ = "v3"

from cryoswath.misc import (
    fill_missing_coords,
    find_region_id,
    load_glacier_outlines,
    rgi_code_translator,
)
from cryoswath.l4 import fill_voids, trend_with_seasons
from dask.distributed import Client, LocalCluster
import numpy as np
import pandas as pd
from pathlib import Path
import rasterio
import sys
from sys import exit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryoswath_paper_workflow.workflow_support import strip_spec_chars
from warnings import catch_warnings, filterwarnings
import xarray as xr


def _filter_observed_data(ds):
    return ds.assign(elev_diff=ds.elev_diff.where(ds.elev_diff_interp_flag == 0))


def _fit_trend_with_seasons(da):
    return da.transpose("time", "y", "x").curvefit(
        coords="time",
        func=trend_with_seasons,
        param_names=[
            "trend",
            "offset",
            "amp_yearly",
            "phase_yearly",
            "amp_semiyr",
            "phase_semiyr",
        ],
        bounds={
            "amp_yearly": (0, np.inf),
            "phase_yearly": [-np.pi, np.pi],
            "amp_semiyr": (0, np.inf),
            "phase_semiyr": [-np.pi, np.pi],
        },
        errors="ignore",
    )


def _calculate_residuals(fit_params, da):
    model_vals = xr.apply_ufunc(
        trend_with_seasons,
        da.time.astype("int"),
        *[fit_params.sel(param=p) for p in fit_params.param],
        dask="allowed",
    )
    return da - model_vals.rename(da.name)


def _filter_uncertain_trends(fit_results):
    mask = np.logical_and(
        # trend variance < 2 (m/yr)^2
        fit_results.curvefit_covariance.sel(cov_i="trend", cov_j="trend") < 2,
        # yearly and semi-yearly amplitude standard deviation < 10 m
        np.logical_and(
            fit_results.curvefit_covariance.sel(cov_i="amp_yearly", cov_j="amp_yearly")
            < 100,
            fit_results.curvefit_covariance.sel(cov_i="amp_semiyr", cov_j="amp_semiyr")
            < 100,
        ),
    )
    return fit_results.where(mask)


def build_trend_georaster(ds):
    # Filter cells with too little data and ensure reasonable dask chunks
    # that are *not* not cut along the time dimension
    ds = ds.chunk(x=100, y=100, time=-1).pipe(_filter_observed_data)
    fit_params = _fit_trend_with_seasons(ds.elev_diff).curvefit_coefficients
    residuals = _calculate_residuals(fit_params, ds.elev_diff)
    outlier = np.abs(residuals) > 2 * residuals.std("time")
    trend_fit_results = (
        _fit_trend_with_seasons(ds.elev_diff.where(~outlier))
        .pipe(_filter_uncertain_trends)
        .sel(param="trend", cov_i="trend", cov_j="trend")
        .drop_vars(["param", "cov_i", "cov_j"])
    )
    rgi_region_code = find_region_id(ds)
    if rgi_region_code[1] == "8":  # special treatment of Scandinavia (all subregions)
        rgi_region_code = "08"
    basin_gdf = load_glacier_outlines(rgi_region_code, "basins", False)
    with LocalCluster() as cluster, Client(cluster):
        tmp = (
            xr.Dataset(
                dict(
                    trend=trend_fit_results.curvefit_coefficients,
                    trend_std=trend_fit_results.curvefit_covariance**0.5,
                    interp_flag=xr.zeros_like(
                        trend_fit_results.curvefit_coefficients
                    ).where(trend_fit_results.curvefit_coefficients.notnull(), -1),
                    ref_elev=ds.elev_diff_ref,
                )
            )
            .rio.write_crs(ds.rio.crs)
            .compute()
        )
        filled = fill_voids(
            tmp,
            "trend",
            "trend_std",
            basin_shapes=basin_gdf,  # pyright: ignore[reportArgumentType]
            discard_deglaciated=False,  # was done already for input data
            outlier_replace=True,
            outlier_limit=2,
            filled_flag="interp_flag",
        )[["trend", "trend_std", "interp_flag"]].transpose("y", "x")
    filled.trend.assign_attrs(_FillValue=np.nan)
    filled.trend_std.assign_attrs(_FillValue=np.nan)
    filled.interp_flag.assign_attrs(_FillValue=-1)
    return filled


def _write_raster_to_disk(raster: xr.Dataset, target: Path):
    raster.rio.to_raster(target)
    with rasterio.open(target, "r+") as raster:
        raster.units = ("m/yr", "m/yr", "")
        raster.descriptions = (
            "Surface elevation trend",
            "Surface elevation trend standard error",
            "Interpolation type",
        )
        raster.update_tags(
            1,
            short_name="trend",
            description="Average surface elevation change rate between July 2010 and November 2024. The value originates from a least-squares regression including yearly and semi-yearly changes.",
        )
        raster.update_tags(
            2,
            short_name="trend_std",
            description="Square root of the trend fit parameter variance.",
        )
        raster.update_tags(
            3,
            short_name="interp_flag",
            description='This flag indicates how voids were filled. -2: "failed" indicates failure of the interpolation (should not occur), -1: "no data" outside of glaciers (overridden by _FillValue), 0: "observed" were not filled, 1: "cell-based" not applicable (should not occur), 2: "basin-based" use a hypsometric model per basin, 3: "group-based" are like (2) but fit the model to all cells in a group of basins, 4: "linear 1 year" not applicable (should not occur), 5: "subregion-wide" does the same as (2) and (3) using all cells per time step, 6: "linear/const cell-based" not applicable (should not occur).',
            flag_values=[-2, -1, 0, 1, 2, 3, 4, 5, 6],
            flag_meanings=[
                "failed",
                "no data",
                "observed",
                "cell-based",
                "basin-based",
                "group-based",
                "linear 1 year",
                "subregion-wide",
                "linear/const cell-based",
            ],
        )


if __name__ == "__main__":
    from argparse import ArgumentParser

    parser = ArgumentParser(description="Calculates surface elevation change rate")
    parser.add_argument("input_path", nargs=1)
    parser.add_argument("output_path", nargs=1)
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    outpath = Path(parser.parse_args().output_path[0])
    if outpath.is_file():
        raise Exception(f"Target {str(outpath)} exists (remove to reproduce).")
    inpath = Path(parser.parse_args().input_path[0])
    if "scandinavia" in inpath.stem.lower():
        while not parser.parse_args().non_interactive:
            answer = input(
                "Processing the three Scandinavian subregions collectively. In this "
                "case, the chosen file name in output_path is ignored and three files "
                "with names like Glacier_surface_elevation_trend_2010-2024"
                "__Scandinavia__<subregion name>__500x500m.tif will be created in the "
                "parent folder of output_path.\nProceed? (y/n): "
            )
            if answer.lower()[0] == "y":
                break
            elif answer.lower()[0] == "n":
                exit(0)
        # note: xarrays combine routines do not work with overlapping
        # arrays. the following will load each dataset, make it
        # one-dimensional, drop all empyt grid cells, merge the three
        # datasets, sort the product such that x and y will be monotonic
        # after unstacking, unstack it, and fill all missing
        # cooridinates with nan values.
        with LocalCluster() as cluster, Client(cluster):
            df = pd.concat(
                [
                    xr.open_dataset(
                        next(
                            inpath.parent.glob(
                                f"*Scandinavia__{strip_spec_chars(subreg)}*"
                            )
                        )
                    )
                    .drop_vars("spatial_ref")
                    .chunk()
                    .transpose(..., "time")
                    .to_dataframe()
                    .dropna(axis=0, subset="elev_diff")
                    for subreg in [rgi_code_translator(f"08-0{i}") for i in range(1, 4)]
                ]
            ).sort_index()
            df_no_time = df[["elev_diff_ref", "basin_id", "group_id"]]
            df_time_dep = df.drop(columns=["elev_diff_ref", "basin_id", "group_id"])
            del df
            ds = (
                xr.merge(
                    [
                        ds.pipe(fill_missing_coords)
                        for ds in [
                            df_time_dep.to_xarray(),
                            df_no_time.to_xarray().isel(time=0),
                        ]
                    ]
                )
                .transpose("time", "y", "x")
                .rio.write_crs(32633)
                .compute()
            )
    else:
        ds = xr.open_dataset(inpath)

    with catch_warnings():
        filterwarnings("ignore", "invalid value encountered in divide", RuntimeWarning)
        raster = build_trend_georaster(ds)

    if "scandinavia" in inpath.stem.lower():
        for o2 in range(1, 4):
            tmp_outpath = outpath.parent / "__".join(
                [
                    "Glacier_surface_elevation_trend_2010-2024",
                    "Scandinavia",
                    strip_spec_chars(rgi_code_translator(f"08-0{o2}")),
                    "500x500m.tif",
                ]
            )
            _write_raster_to_disk(
                raster.rio.clip(
                    [
                        load_glacier_outlines(
                            f"08-0{o2}", "basins", union=True, crs=raster.rio.crs
                        )
                    ]
                ),
                tmp_outpath,
            )
    else:
        _write_raster_to_disk(raster, outpath)
