from cryoswath.l4 import append_elevation_reference
from dask.array import map_overlap, nanmean, where
from dask.distributed import Client, LocalCluster, progress
import numpy as np
import pandas as pd
import rioxarray as rioxr
from scipy.ndimage import maximum_filter, percentile_filter
from cryoswath_paper_workflow.workflow_support import (
    out_to_snakemake_log_or_fallback_stdout,
)
from typing import Protocol, runtime_checkable


@runtime_checkable
class snakemake_mock(Protocol):
    input: dict[str, str]
    output: dict[int, str]


snakemake = globals().get("snakemake", snakemake_mock)


def qqrange(arr: np.ndarray) -> np.ndarray:
    window = (31, 31)
    finite = np.isfinite(arr)
    p10 = percentile_filter(
        np.where(finite, arr, np.inf),
        percentile=10,
        size=window,
        mode="nearest",
    )
    p90 = percentile_filter(
        np.where(finite, arr, -np.inf),
        percentile=90,
        size=window,
        mode="nearest",
    )
    has_valid = maximum_filter(finite, size=window, mode="nearest")
    return np.where(has_valid, p90 - p10, np.nan)


def build_metrics_graph(tif_path: str):
    ds = rioxr.open_rasterio(
        tif_path, band_as_variable=True, chunks={"y": 512, "x": 512}
    )
    ds = (
        ds.rename_vars(  # pyright: ignore[reportAttributeAccessIssue]
            {k: v.attrs["short_name"] for k, v in ds.data_vars.items()}  # pyright: ignore[reportAttributeAccessIssue]
        )
        .pipe(
            append_elevation_reference,
            ref_elev_name="ref_elev",
            dem_file_name_or_path=snakemake.input["dem"],
        )
        .chunk({"y": 512, "x": 512})
    )

    ref = ds.ref_elev.data
    flag = ds.interp_flag.data
    valid = flag >= 0

    qq = map_overlap(
        qqrange, ref, depth=(15, 15), boundary="nearest", trim=True, dtype=np.float32
    )

    coverage = (flag == 0).sum() / valid.sum()
    ruggedness = nanmean(where(valid, qq, np.nan))
    return coverage, ruggedness


def main():
    with (
        LocalCluster(n_workers=snakemake.threads) as cluster,
        Client(cluster) as client,
    ):
        keys, graphs = [], []
        for file in snakemake.input:
            if "arcticdem" in file:
                continue
            keys.append(file.split("__")[-3:-1])
            graphs.append(build_metrics_graph(file))

        futures = client.compute(graphs)
        progress(futures, interval="10s")
        vals = client.gather(futures)

    df = pd.DataFrame(
        vals,  # type: ignore
        index=pd.MultiIndex.from_tuples(keys),
        columns=["coverage", "ruggedness"],
    )
    print(df)
    df.to_csv(snakemake.output[0])


if __name__ == "__main__":
    with out_to_snakemake_log_or_fallback_stdout(
        globals().get("snakemake"), delete_old=True
    ):
        main()
