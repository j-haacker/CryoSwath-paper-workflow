import numpy as np
import pickle
from pathlib import Path
import rasterio as rio
from cryoswath.misc import rgi_code_translator
from cryoswath_paper_workflow.workflow_support import (
    rgi_uncertainty,
    snakemake_fallback_builder,
    out_to_snakemake_log_or_fallback_stdout,
    o1o2reg_tuple_list,
    strip_spec_chars,
    project_path,
)

snakemake_fallback = snakemake_fallback_builder(globals())


def main():
    trend_root = Path(
        snakemake_fallback(
            "params", "trend_root", str(project_path("data", "L4"))
        )
    )
    with open(
        snakemake_fallback(
            "input",
            "o2_areas_rgi",
            str(project_path("resources", "subregion_area_totals_from_RGI.pkl")),
        ),
        "rb",
    ) as f:
        o2_areas_rgi = pickle.load(f)
    with open(
        snakemake_fallback(
            "output", 0, str(project_path("results", "tabA2__subregion_overview.tex"))
        ),
        "w",
    ) as texfile:
        print(r"\begin{tabular}{llrrrrr}\tophline", file=texfile)
        print(
            "ID",
            "Name",
            "EPSG",
            "Covered area",
            "RGI area",
            "$u_{A1}$",
            "$u_{A2}$",
            sep=" & ",
            end=" \\\\\n",
            file=texfile,
        )
        print(r"\middlehline", file=texfile)
        for o1, o2list in o1o2reg_tuple_list:
            o1name = rgi_code_translator(f"{o1:02d}")
            for o2 in o2list:
                region_code = f"{o1:02d}-{o2:02d}"
                area_rgi = o2_areas_rgi.loc[o1, o2]
                rgi_unc = rgi_uncertainty((o1, o2))
                raster = rio.open(
                    str(
                        trend_root
                        / "__".join(
                            [
                                "Glacier_surface_elevation_trend_2010-2024",
                                strip_spec_chars(o1name),
                                strip_spec_chars(rgi_code_translator(region_code)),
                                "500x500m.tif",
                            ]
                        )
                    )
                )
                area_cs2 = (~np.isnan(raster.read(1))).sum() / 4
                print(
                    region_code,
                    rgi_code_translator(region_code),
                    str(raster.crs).split(":")[1],
                    round(area_cs2),
                    round(area_rgi),
                    round(np.abs(area_rgi - area_cs2)),
                    round(rgi_unc),
                    sep=" & ",
                    end=" \\\\\n",
                    file=texfile,
                )
        print(r"\bottomhline\end{tabular}", end="", file=texfile)


if __name__ == "__main__":
    with out_to_snakemake_log_or_fallback_stdout(globals().get("snakemake"), delete_old=True):
        main()
