"""Generate the Arctic-wide elevation time-series figure."""

import matplotlib as mpl
import matplotlib.pyplot as plt
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.deterministic import TimeTrend, CalendarFourier
from cryoswath_paper_workflow.workflow_support import (
    out_to_snakemake_log_or_fallback_stdout,
    project_path,
    snakemake_fallback_builder,
)

mpl.rcParams["svg.fonttype"] = "none"

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
            "input",
            "avg_elev_tbl",
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

    # drop Alaska North due to failing interpolation
    df.loc(1)[:, 1] = df.loc(1)[:, 1].drop(1, axis=1, level=2)
    df.dropna(axis=1, inplace=True)

    quarterly_total = (
        (
            (df["elevation"] * o2_areas).sum(axis=1)
            / ((~df["elevation"].iloc[0, :].isnull()) * o2_areas).sum()
        )
        .resample("QS-AUG", label="left")
        .first()
    )

    cs2_ts = (df["elevation"] * o2_areas).sum(axis=1) / (
        (~df["elevation"].iloc[0, :].isnull()) * o2_areas
    ).sum()

    annual_cs2 = quarterly_total[0::4].diff().shift(-1).dropna()

    area_arctic = ((~df["uncertainty"].iloc[0, :].isnull()) * o2_areas).dropna().sum()

    fig, ax = plt.subplots(figsize=(12 / 2.54, 12 / 2.54 * 9 / 16))
    cs2_ts.plot(ax=ax, c="tab:gray", lw=0.8, label="Monthly data", zorder=0.5)
    plt.fill_between(
        df.index,
        (
            (df["elevation"] * o2_areas).sum(axis=1)
            / ((~df["elevation"].iloc[0, :].isnull()) * o2_areas).sum()
            - (((df["uncertainty"] * o2_areas) ** 2).sum(axis=1)) ** 0.5
            / ((~df["elevation"].iloc[0, :].isnull()) * o2_areas).sum()
        ),
        (
            (df["elevation"] * o2_areas).sum(axis=1)
            / ((~df["elevation"].iloc[0, :].isnull()) * o2_areas).sum()
            + (((df["uncertainty"] * o2_areas) ** 2).sum(axis=1)) ** 0.5
            / ((~df["elevation"].iloc[0, :].isnull()) * o2_areas).sum()
        ),
        fc="tab:gray",
        ec="none",
        alpha=0.3,
        zorder=0,
    )
    cmap = plt.colormaps["RdYlBu"]
    annual_cs2_lower = annual_cs2.min()
    plt.bar(
        x=annual_cs2.index + pd.DateOffset(months=6),
        height=-annual_cs2.values,
        width=12,
        bottom=cs2_ts.resample("QS-AUG", label="left").first().iloc[0]
        + annual_cs2.cumsum(),
        color=cmap(0.5 - annual_cs2 / annual_cs2_lower / 2),
        zorder=0,
    )
    norm = mpl.colors.Normalize(vmin=annual_cs2.min(), vmax=-annual_cs2.min())
    cax = fig.add_axes((0.18, 0.23, 0.4, 0.03))
    cbar = fig.colorbar(
        mpl.cm.ScalarMappable(norm=norm, cmap=cmap), cax=cax, orientation="horizontal"
    )
    cbar.ax.set_title("Yearly elevation change, m/yr", fontsize=8, pad=3)
    cbar.ax.tick_params(labelsize=8, direction="in")
    tmp = quarterly_total.copy()
    tmp.index = tmp.index + pd.DateOffset(day=15)
    tmp.plot(ax=ax, label="Decimated data", zorder=3)
    fit_res = fit_trend(quarterly_total)
    deseasoned = pd.DataFrame(
        0, index=quarterly_total.index, columns=fit_res.model.exog_names
    )
    deseasoned[fit_res.model.exog_names[:2]] = fit_res.model.exog[:, :2]
    deseasoned = fit_res.predict(deseasoned)
    (deseasoned + fit_res.resid).plot(
        ax=ax, c="w", alpha=0.8, marker=".", ms=6, ls="", zorder=6
    )
    (deseasoned + fit_res.resid).plot(
        ax=ax,
        c="tab:red",
        marker=".",
        ms=3,
        ls="",
        label="Decimated data\nminus fitted periodicity",
        zorder=7,
    )
    deseasoned.plot(ax=ax, c="white", alpha=0.8, lw=4, zorder=4)
    deseasoned.plot(
        ax=ax, c="tab:green", lw=2, ls="dashed", label="Fitted trend", zorder=5
    )
    ax.legend(fontsize=8, loc="upper right")
    ax.tick_params(axis="both", labelsize=8)
    ax.set_xlabel("")
    ax.set_ylabel("Surface elevation change, m", fontsize=10)
    fig.tight_layout()
    project_path("figures").mkdir(exist_ok=True)
    plt.savefig(
        snakemake_fallback(
            "output",
            0,
            str(project_path("figures", "fig04__arctic-wide_time_series.pdf")),
        )
    )


def fit_trend(ts):
    return sm.OLS(
        ts,
        pd.concat(
            [
                TimeTrend(True, 1).in_sample(ts.index),
                CalendarFourier("YE", 2).in_sample(ts.index),
            ],
            axis=1,
        ),
    ).fit()


if __name__ == "__main__":
    with out_to_snakemake_log_or_fallback_stdout(
        globals().get("snakemake"), delete_old=True
    ):
        main()
