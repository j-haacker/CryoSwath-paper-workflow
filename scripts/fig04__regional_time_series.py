#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "cryoswath",
#     "matplotlib",
#     "pandas",
#     "seaborn",
# ]
#
# [tool.uv.sources]
# cryoswath = { path = "../.." }
# ///

from cryoswath.misc import (
    rgi_path,
    rgi_code_translator,
    load_glacier_outlines,
)
import matplotlib as mpl
import matplotlib.pyplot as plt
import pandas as pd
from pathlib import Path
import seaborn as sns
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryoswath_paper_workflow.workflow_support import (
    out_to_snakemake_log_or_fallback_stdout,
    project_path,
    snakemake_fallback_builder,
)

mpl.rcParams["svg.fonttype"] = "none"
sns.set_theme()
sns.set_context("paper")

snakemake_fallback = snakemake_fallback_builder(globals())

def main():
    o2_areas = pd.read_csv(
        snakemake_fallback(
            "input",
            "area_tbl",
            str(project_path("data", "L4", "o2region__area_km2.csv")),
        ),
        index_col=["o1", "o2"],
    ).area_km2
    o2_areas.index.set_names([None, None], inplace=True)


    df = pd.read_csv(
        snakemake_fallback(
            "input", "avg_elev_tbl",
            str(
                project_path(
                    "data",
                    "L4",
                    "Arctic_monthly_avg_glacier_surface_elevation_wrt_2010_per_RGI_o2region__meter.csv",
                )
            ),
        ),
        index_col=0,
        header=[0, 1, 2],
        skiprows=[3],
        parse_dates=True,
    ).rename_axis("time")
    df.columns = pd.MultiIndex.from_tuples(
        [[int(ix) if len(ix) <= 2 else ix for ix in tup] for tup in df.columns]
    )
    df = df.swaplevel(1, 2, axis=1)
    df = df.swaplevel(0, 1, axis=1)
    df.dropna(axis=0, how="any", inplace=True)
    df = df.iloc[2:]

    for i, ax in zip([1] + list(range(3, 10)), plt.subplots(4, 2, figsize=(16/2.54, 12/2.54), sharex=True, sharey=True)[1].flatten()):
        if i == 2:
            continue
        plt.sca(ax)
        plt.fill_between(
            df.index,
            (
                (df["elevation", i] * o2_areas.loc[i]).sum(axis=1)
                / ((~df["elevation", i].iloc[0, :].isnull()) * o2_areas.loc[i]).sum()
                - (((df["uncertainty", i] * o2_areas.loc[i]) ** 2).sum(axis=1)) ** 0.5
                / ((~df["elevation", i].iloc[0, :].isnull()) * o2_areas.loc[i]).sum()
            ),
            (
                (df["elevation", i] * o2_areas.loc[i]).sum(axis=1)
                / ((~df["elevation", i].iloc[0, :].isnull()) * o2_areas.loc[i]).sum()
                + (((df["uncertainty", i] * o2_areas.loc[i]) ** 2).sum(axis=1)) ** 0.5
                / ((~df["elevation", i].iloc[0, :].isnull()) * o2_areas.loc[i]).sum()
            ),
            fc="tab:gray",
            ec="none",
            alpha=0.5,
        )
        plt.plot(
            df.index,
            (df["elevation", i] * o2_areas.loc[i]).sum(axis=1)
            / ((~df["elevation", i].iloc[0, :].isnull()) * o2_areas.loc[i]).sum(),
        )
        plt.ylim([-20, 5])
        region_name = rgi_code_translator(f"{i:02d}") if i != 7 else "Svalbard"
        plt.annotate(
            region_name,
            xy=(0, 0), xycoords="axes fraction",
            xytext=(0.5, 1), textcoords="offset fontsize",
            fontsize='medium', verticalalignment='top', fontfamily='serif',
            bbox=dict(facecolor='0.7', edgecolor='none', pad=3.0)
        )
    plt.tight_layout()
    plt.annotate(
        'Surface elevation change, m',
        xy=(0.01, 0.5), xycoords="figure fraction",
        va='center', rotation='vertical')
    plt.savefig(
        snakemake_fallback(
            "output",
            0,
            str(project_path("figures", "fig04__regional_time_series.pdf")),
        )
    )


if __name__ == "__main__":
    with out_to_snakemake_log_or_fallback_stdout(globals().get("snakemake"), delete_old=True):
        main()
