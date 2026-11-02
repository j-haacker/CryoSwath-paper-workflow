#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "cryoswath",
#     "geopandas>=1.1.2",
#     "matplotlib",
#     "seaborn",
#     "stackstac>=0.5.1",
# ]
#
# [tool.uv.sources]
# cryoswath = { path = "../Documents/PhD/projects/2023__cryoswath", editable = true }
# ///

from pathlib import Path
import sys
from typing import Any

import geopandas as gpd
import matplotlib.pyplot as plt
import seaborn as sns
from cryoswath import l1b
from cryoswath.misc import download_dem, gauss_filter_DataArray

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cryoswath_paper_workflow.workflow_support import (
    out_to_snakemake_log_or_fallback_stdout,
    project_path,
    snakemake_fallback_builder,
    warn_if_esa_credentials_missing_for_l1b,
)

sns.set_theme()
sns.set_context("paper")

snakemake_fallback = snakemake_fallback_builder(globals())

OUTPUT_FIGURE = str(project_path("figures", "fig01__example__wf_start.pdf"))
PANEL_LABELS = ("a", "b")
WAVEFORM_SPECS = (
    {
        "track_id": "2020-08-02 15:35:52",
        "waveform_selection": "20200802T153837.258820992",
        "drop_outside": False,
    },
    {
        "track_id": "20140517T225409",
        "waveform_selection": "20140517T225448.610051968",
        "drop_outside": False,
        "use_original_noise_estimates": True,
        "append_best_fit_phase_index": True,
    },
)
PLOT_PROPERTIES: dict[str, dict[str, Any]] = {
    "swath": {
        "color": sns.color_palette()[0],
        "marker": ".",
        "markersize": 5,
        "linewidth": 1,
    },
    "poca": {
        "color": sns.color_palette()[2],
        "marker": "o",
        "markersize": 5,
        "linewidth": 1,
    },
    "excluded": {
        "color": sns.color_palette()[1],
        "marker": "x",
        "markersize": 5,
        "linewidth": 0.6,
    },
    "omitted": {
        "hatch": "///",
        "linewidth": 0.4,
        "edgecolor": "xkcd:light grey",
        "facecolor": "none",
    },
    "threshold": {
        "hatch": "\\\\\\",
        "linewidth": 0.4,
        "edgecolor": "xkcd:light grey",
        "facecolor": "none",
    },
}


def load_waveform(spec: dict[str, Any]):
    kwargs = spec.copy()
    track_id = kwargs.pop("track_id")
    append_best_fit_phase_index = kwargs.pop("append_best_fit_phase_index", False)

    waveform = l1b.from_id(track_id, **kwargs)
    if append_best_fit_phase_index:
        download_dem(
            gpd.points_from_xy(
                waveform.lon_20_ku, waveform.lat_20_ku, crs=4326
            ).to_crs(3413).buffer(30_000)
        )
        waveform = waveform.pipe(l1b.append_best_fit_phase_index)
    return waveform


def plot_coherence(
    waveform,
    *,
    ax: plt.Axes,
    plot_properties: dict[str, dict[str, Any]] | None = None,
):
    if plot_properties is None:
        plot_properties = PLOT_PROPERTIES

    h_smooth = gauss_filter_DataArray(
        waveform.coherence_waveform_20_ku,
        "ns_20_ku",
        35,
        35,
    ).plot(c=".7", label="Low-pass", ax=ax)[0]
    handles = [h_smooth]

    if "exclude_mask" in waveform:
        excluded = waveform.where(waveform.exclude_mask)
        (h_excluded,) = ax.plot(
            excluded.ns_20_ku,
            excluded.coherence_waveform_20_ku[0],
            ls="",
            label="Discarded",
            **plot_properties["excluded"],
        )
        swath = waveform.where(~waveform.exclude_mask)
        (h_swath,) = ax.plot(
            swath.ns_20_ku,
            swath.coherence_waveform_20_ku[0],
            ls="",
            label="Selected",
            **plot_properties["swath"],
        )
        handles = [h_swath, h_excluded, h_smooth]
    else:
        (h_all,) = ax.plot(
            waveform.ns_20_ku,
            waveform.coherence_waveform_20_ku[0],
            ls="",
            label="All",
            **plot_properties["swath"],
        )
        handles = [h_all, h_smooth]

    try:
        poca = waveform.sel(ns_20_ku=waveform.poca_idx)
    except KeyError:
        pass
    else:
        (h_poca,) = ax.plot(
            poca.ns_20_ku,
            poca.coherence_waveform_20_ku[0],
            ls="",
            label="POCA",
            **plot_properties["poca"],
        )
        handles.append(h_poca)

    ax.set_xlim([waveform.ns_20_ku[0], waveform.ns_20_ku[-1]])
    ax.set_ylim([0, 1.05])
    ax.set_xlabel("Range wrt. first sample, m")
    ax.set_ylabel("Coherence")
    ax.legend(handles=handles, loc="lower right")
    ax.set_title("")


def add_panel_labels(axes):
    for label, ax in zip(PANEL_LABELS, axes):
        ax.annotate(
            label,
            xy=(0, 1),
            xycoords="axes fraction",
            xytext=(+0.5, -0.5),
            textcoords="offset fontsize",
            fontsize="medium",
            verticalalignment="top",
            fontfamily="serif",
            fontweight="bold",
            bbox=dict(facecolor=(1, 1, 1, 0.4), edgecolor="k", pad=3.0),
        )


def make_figure():
    fig, axes = plt.subplots(2, figsize=(12 / 2.54, 12 / 2.54))
    waveforms = [load_waveform(spec) for spec in WAVEFORM_SPECS]

    for waveform, ax in zip(waveforms, axes):
        plot_coherence(waveform, ax=ax)

    axes[1].get_legend().remove()
    axes[1].set_xticklabels(
        [f"{int(label.get_text()) * 0.2342:.0f}" for label in axes[1].get_xticklabels()]
    )
    axes[0].set_xlabel("Sample number")
    axes[0].tick_params(labeltop=True, labelbottom=False)
    axes[0].xaxis.set_label_position("top")
    add_panel_labels(axes)
    fig.tight_layout()
    return fig


def main():
    warn_if_esa_credentials_missing_for_l1b(
        [spec["track_id"] for spec in WAVEFORM_SPECS]
    )
    fig = make_figure()
    output_path = Path(snakemake_fallback("output", 0, OUTPUT_FIGURE))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)


if __name__ == "__main__":
    with out_to_snakemake_log_or_fallback_stdout(
        globals().get("snakemake"), delete_old=True
    ):
        main()
