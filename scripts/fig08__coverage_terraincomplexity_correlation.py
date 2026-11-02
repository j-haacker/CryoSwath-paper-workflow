import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
import statsmodels.api as sm
from cryoswath_paper_workflow.workflow_support import (
    out_to_snakemake_log_or_fallback_stdout,
    to_yaml,
)
from typing import Protocol, runtime_checkable


@runtime_checkable
class snakemake_mock(Protocol):
    input: dict[int, str]
    output: dict[str, str]


snakemake = globals().get("snakemake", snakemake_mock)


sns.set_theme()


def main():
    df = pd.read_csv(snakemake.input[0], index_col=[0, 1])
    df["coverage"] *= 100  # Fit and plot coverage in percent.
    fit_res = sm.OLS(df.coverage, sm.tools.add_constant(df.ruggedness / 100)).fit()
    print(fit_res.summary())
    to_yaml(
        {
            (k if k != "ruggedness" else "trend"): {
                "value": float(fit_res.params[k]),
                "uncertainty": 2 * float(fit_res.bse[k]),  # 2 sigma
                "units": [r"\%"],  # for the trend: per 100 m "ruggedness"
            } for k in fit_res.params.keys()
        },
        snakemake.output["fit"]
    )
    plt.scatter(x=df["ruggedness"], y=df["coverage"])
    xmin, xmax = df.ruggedness.min(), df.ruggedness.max()
    plt.plot(
        [xmin, xmax],
        [
            (fit_res.params.const + fit_res.params.ruggedness * x / 100)
            for x in [xmin, xmax]
        ],
    )
    plt.ylabel("Coverage, %")
    plt.xlabel("Footprint topography 10-90-span, m")
    plt.savefig(snakemake.output["fig"])


if __name__ == "__main__":
    with out_to_snakemake_log_or_fallback_stdout(
        globals().get("snakemake"), delete_old=True
    ):
        main()
