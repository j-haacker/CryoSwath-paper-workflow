from jinja2 import Environment
import os
import pandas as pd

from cryoswath_paper_workflow.workflow_support import (
    out_to_snakemake_log_or_fallback_stdout,
    project_path,
    snakemake_fallback_builder,
)
import yaml

snakemake_fallback = snakemake_fallback_builder(globals())


import numpy as np


def precision(val):
    return max(0, round(1 - np.log10(val)))


from typing import Literal


def latex_format(
    value_dict: dict,
    style: Literal["full", "value", "unc", "nounits"] = "full",
    absolute: bool = False,
    prec: int | None = None,
    in_math: bool = False,
):
    value = value_dict["value"]
    if absolute:
        value = abs(value)
    if "uncertainty" in value_dict and value_dict["uncertainty"] is not None:
        if prec is None:
            prec = precision(value_dict["uncertainty"])
        unc_str = f"{value_dict['uncertainty']:.{prec}f}"
        if style == "unc":
            return f"${unc_str}$"
    val_str = f"{value:.{0 if prec is None else prec}f}"
    if style != "value" and "unc_str" in locals():
        val_str += f"\\pm{unc_str}$"  # pyright: ignore[reportPossiblyUnboundVariable]
    elif not in_math:
        val_str += "$"
    if "units" in value_dict and style != "nounits":
        val_str += ("" if value_dict["units"][0] in [r"^\circ"] else "~") + "~".join(
            [f"\\unit{{{u}}}" for u in value_dict["units"]]
        )
    return ("" if in_math else "$") + val_str


def row_to_value(row_dict: dict, which: Literal["mass", "spec"]) -> dict:
    if which == "mass":
        return {
            "value": row_dict["mass"],
            "uncertainty": row_dict["m_err"],
            "units": ["Gt", "yr^{-1}"],
        }
    else:
        return {
            "value": row_dict["specific"],
            "uncertainty": row_dict["sp_err"],
            "units": ["m", "yr^{-1}"],
        }


def format_single_MB_val(value: float, prec: int, absolute: bool = False) -> str:
    if absolute:
        value = abs(value)
    return f"${value:.{prec}f}$"r"~\unit{Gt}~\unit{yr^{-1}}"


def format_single_percentage(value: float, prec: int) -> str:
    formatted = f"{100*value:.{prec}f}"
    # Avoid implying none or all when rounding a proportion between the endpoints.
    if 0 < value < 1:
        if float(formatted) == 0:
            formatted = f"<{10**-prec:.{prec}f}"
        elif float(formatted) == 100:
            formatted = f">{100 - 10**-prec:.{prec}f}"
    return f"${formatted}$"r"~\unit{\%}"


def prepend_figure_path(filename: str) -> str:
    return os.path.join("figures", filename)


def main():
    env = Environment(
        autoescape=False,
        block_start_string=r"\BLOCK{",
        block_end_string="}",
        variable_start_string=r"\VAR{",
        variable_end_string="}",
        comment_start_string=r"\#{",
        comment_end_string="}",
    )
    env.filters["fig"] = prepend_figure_path
    env.filters["fmt"] = latex_format
    env.filters["r2v"] = row_to_value
    env.filters["MB"] = format_single_MB_val
    env.filters["P"] = format_single_percentage

    with open(
        snakemake_fallback(
            "input", "template", project_path("paper", "paper__template.tex.j2")
        )
    ) as template_file:
        template = env.from_string(template_file.read())

    with (
        open(
            snakemake_fallback(
                "input",
                "value_collection",
                str(project_path("results", "result__value_collection.yaml")),
            ),
            "r",
        ) as in_coll,
        open(
            snakemake_fallback(
                "input",
                "o1_trend_tbl",
                str(project_path("results", "tab01__subregion_trend_table.tex")),
            ),
            "r",
        ) as in_tab01,
        open(
            snakemake_fallback(
                "input",
                "refJG_tbl",
                str(project_path("results", "tab03__JG_comparison.tex")),
            ),
            "r",
        ) as in_tab03,
        open(
            snakemake_fallback(
                "input",
                "one_yr_corr",
                str(project_path("results", "one_year_error_correlation.txt")),
            ),
            "r",
        ) as in_1yr_corr,
        open(
            snakemake_fallback(
                "input",
                "barnes",
                str(project_path("results", "closeup__icecap__barnes.yaml")),
            ),
            "r",
        ) as in_barnes,
        open(
            snakemake_fallback(
                "input",
                "penny",
                str(project_path("results", "closeup__icecap__penny.yaml")),
            ),
            "r",
        ) as in_penny,
        open(
            snakemake_fallback(
                "input",
                "sukkerqara",
                str(project_path("results", "closeup__icecap__sukkerqara.yaml")),
            ),
            "r",
        ) as in_sukkerqara,
        open(
            snakemake_fallback(
                "input",
                "scandinavian",
                str(project_path("results", "closeup__icecap__scandinavian.yaml")),
            ),
            "r",
        ) as in_scandinavian,
        open(
            snakemake_fallback(
                "input",
                "fig16_clip",
                str(project_path("results", "vatna_deviation_analysis.yaml")),
            ),
            "r",
        ) as in_fig16_clip,
        open(
            snakemake_fallback(
                "input",
                "cover_fit",
                str(project_path("results", "coverage_terraincomplexity_correlation.yaml")),
            ),
            "r",
        ) as in_cover_fit,
        open(
            snakemake_fallback(
                "input",
                "subreg_tbl",
                str(project_path("results", "tabA2__subregion_overview.tex")),
            ),
            "r",
        ) as in_tabA2,
        open(snakemake_fallback("output", 0, str(project_path("paper", "manuscript.tex"))), "w")
        as out,
    ):
        omitted_df = pd.read_csv(
            snakemake_fallback(
                "input",
                "omitted",
                str(project_path("results", "omitted_subregions.csv")),
            ),
            index_col=0,
        )
        scandi = yaml.safe_load(in_scandinavian)
        collection = yaml.safe_load(in_coll)
        collection.update(
            {
                "omitted_names": (
                    ", ".join(omitted_df.subreg.values[:-1])
                    + ", and "
                    + omitted_df.subreg.iat[-1]
                ),  # pyright: ignore[reportOperatorIssue]
                "omitted_perc": (
                    ", ".join([f"{x:.{precision(x)}f}" for x in 100 * omitted_df.area_o1share.values[:-1]]) # pyright: ignore[reportOperatorIssue]
                    + ", and "
                    + next(f"{x:.{precision(x)}f}" for x in 100 * omitted_df.area_o1share.values[[-1]]) # pyright: ignore[reportOperatorIssue]
                ),
                "corr_1yr": {"value": float(in_1yr_corr.read())},
                "barnes": yaml.safe_load(in_barnes),
                "penny": yaml.safe_load(in_penny),
                "sukkerqara": yaml.safe_load(in_sukkerqara),
                "vatna": yaml.safe_load(in_fig16_clip),
            }
        )
        scandi_tex = (
            r"\begin{tabular}{l@{\;\;}>{$}r<{$}@{ $\pm$ }>{$}l<{$}}"
            "\n\\tophline\n"
            r"Glacier & \multicolumn{2}{l}{Thinning rate} \\"
            "\n\\middlehline\n"
            + " \\\\\n".join(
                [
                    " & ".join([l, *list(map("{:.2f}".format, row.values))])  # type: ignore
                    for l, row in pd.DataFrame.from_dict(scandi)
                    .T[["specific", "sp_err"]]
                    .abs()  # thinning -> minus sign implied
                    .iterrows()
                ]
            )
            +  r"\\"
            "\n\\bottomhline\n"
            r"\end{tabular}"
        )
        out.write(
            template.render(
                coll=collection,
                tab01=in_tab01.read(),
                trends=pd.read_csv(
                    snakemake_fallback(
                        "input",
                        "trend_tbl",
                        str(project_path("results", "result__regional_trends.csv")),
                    ),
                    index_col=0,
                    header=[0, 1],
                )
                .stack(level=0)
                .to_dict(orient="index"),  # pyright: ignore[reportCallIssue]
                grnl=pd.read_csv(
                    snakemake_fallback(
                        "input",
                        "grnl_tbl",
                        str(project_path("results", "result__greenland_trends.csv")),
                    ),
                    index_col=0,
                    header=[0, 1],
                )
                .stack(level=0)
                .to_dict(orient="index"),  # pyright: ignore[reportCallIssue]
                tab02=scandi_tex,
                tab03=in_tab03.read(),
                vatna_df=pd.read_csv(
                    snakemake_fallback(
                        "input",
                        "isl_disc",
                        str(project_path("results", "vatna_deviation_analysis.csv")),
                    ),
                    index_col=0,
                ),
                cover_df = pd.read_csv(
                    snakemake_fallback(
                        "input",
                        "cov_disc",
                        str(project_path("results", "coverage_analysis.csv")),
                    ),
                    index_col=[0, 1],
                ),
                cover_fit=yaml.safe_load(in_cover_fit),
                tabA2=in_tabA2.read(),
            ).replace("\\cs", "\\mbox{CryoSat-2}")  # avoid macro-usage
        )


if __name__ == "__main__":
    with out_to_snakemake_log_or_fallback_stdout(globals().get("snakemake"), delete_old=True):
        main()
