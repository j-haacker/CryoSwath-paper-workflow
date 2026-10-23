"""Snakemake workflow for the article figures, tables, and manuscript."""

configfile: "config/snakemake.yaml"

include: "rules/definitions.smk"


rule all:
    input:
        "paper/manuscript.pdf",


rule publication_reproduction:
    input:
        PUBLICATION_REPRODUCTION_OUTPUTS,


rule nsidc_cookies:
    output:
        ".nsidc_cookies",
    log:
        "<logs>/nsidc_cookies.log",
    script:
        script_path("nsidc_cookies.py")


rule rgi_global_attr:
    input:
        ancient(".nsidc_cookies"),
    output:
        "<resources>/auxiliary/RGI/RGI2000-v7.0-G-global-attributes.csv",
    log:
        "<logs>/rgi_global_attr.log",
    shell:
        """
        wget -O tmp.zip \
            --load-cookies .nsidc_cookies \
            --no-check-certificate \
            --auth-no-challenge=on \
            -e robots=off \
            "{RGI_GLOBAL_ATTRS_URL}/RGI2000-v7.0-G-global-attributes.csv.zip" > {log} 2>&1
        filepath={output}
        unzip -o tmp.zip -d ${{filepath%/*}} >> {log} 2>&1
        rm tmp.zip
        """


rule rgi_glacier_shapefiles:
    input:
        ancient(".nsidc_cookies"),
    output:
        "<resources>/auxiliary/RGI/RGI2000-v7.0-G-{token}/RGI2000-v7.0-G-{token}.shp",
    log:
        "<logs>/rgi_glacier_shapefiles__{token}.log",
    shell:
        """
        wget -O tmp_G_{wildcards.token}.zip \
            --load-cookies .nsidc_cookies \
            --no-check-certificate \
            --auth-no-challenge=on \
            -e robots=off \
            "{RGI_REGIONAL_URL}/RGI2000-v7.0-G/RGI2000-v7.0-G-{wildcards.token}.zip" > {log} 2>&1
        filepath={output}
        unzip -o -d ${{filepath%/*}} tmp_G_{wildcards.token}.zip >> {log} 2>&1
        rm tmp_G_{wildcards.token}.zip
        """


rule rgi_complex_shapefiles:
    input:
        ancient(".nsidc_cookies"),
    output:
        "<resources>/auxiliary/RGI/RGI2000-v7.0-C-{token}/RGI2000-v7.0-C-{token}.shp",
    log:
        "<logs>/rgi_complex_shapefiles__{token}.log",
    shell:
        """
        wget -O tmp_C_{wildcards.token}.zip \
            --load-cookies .nsidc_cookies \
            --no-check-certificate \
            --auth-no-challenge=on \
            -e robots=off \
            "{RGI_REGIONAL_URL}/RGI2000-v7.0-C/RGI2000-v7.0-C-{wildcards.token}.zip" > {log} 2>&1
        filepath={output}
        unzip -o -d ${{filepath%/*}} tmp_C_{wildcards.token}.zip >> {log} 2>&1
        rm tmp_C_{wildcards.token}.zip
        """


rule download_cryoswath_aux_data:
    output:
        CRYOSWATH_AUX_FILES,
    log:
        "<logs>/setup_0.log",
    shell:
        """
        cryoswath download-aux-data  >> {log} 2>&1
        """


rule o2reg_filename_token_list:
    output:
        "<resources>/filename_tokens.txt",
    log:
        "<logs>/o2reg_filename_token_list.log",
    run:
        make_o2reg_filename_token_list(output[0])


if PUBLICATION_ARTIFACT_SOURCE != "downloaded":

    rule download_external_figures:
        output:
            MANUSCRIPT_EXTERNAL_FIGURES,
        params:
            archive=pathvar_path("<resources>/downloads/downloaded_publication_data.zip"),
            url=PUBLICATION_DATA_URL,
        log:
            "<logs>/download_external_figures.log",
        run:
            download_archive_members(
                url=params.url,
                archive_path=params.archive,
                destinations=list(output),
                log_path=log[0],
            )


rule download_monthly_dataset:
    output:
        "<resources>/monthly_dataset/Glacier_surface_elevation__{token}__monthly_500x500m.nc",
    wildcard_constraints:
        token="|".join(map(re.escape, filename_tokens)),
    log:
        "<logs>/download_monthly_dataset__{token}.log",
    script:
        script_path("download_monthly_elevations.py")


rule download_trends_dataset:
    input:
        [
            str(TREND_DATASET_LOCAL_DIR / Path(pathvar_path(path)).name)
            for path in TREND_DATASET_OUTPUTS
        ] if TREND_DATASET_LOCAL_DIR else [],
    output:
        TREND_DATASET_OUTPUTS,
    params:
        archive=pathvar_path("<resources>/downloads/trends_dataset.zip"),
        url=TREND_DATASET_ARCHIVE_URL,
    log:
        "<logs>/download_trends_dataset.log",
    run:
        if TREND_DATASET_LOCAL_DIR:
            import shutil

            Path(log[0]).parent.mkdir(parents=True, exist_ok=True)
            with Path(log[0]).open("w", encoding="utf-8") as handle:
                handle.write(f"Local trend dataset source: {TREND_DATASET_LOCAL_DIR}\n")
                for source, destination in zip(input, output):
                    Path(destination).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
                    handle.write(f"Copied {source} to {destination}\n")
        else:
            download_archive_members(
                url=params.url,
                archive_path=params.archive,
                destinations=list(output),
                log_path=log[0],
            )


if PUBLICATION_ARTIFACT_SOURCE == "produced":

    rule fig02__coherence_waveform_examples:
        input:
            CRYOSWATH_AUX_FILES,
        output:
            "paper/figures/fig02__example__wf_start.pdf",
        log:
            "<logs>/fig02__coherence_waveform_examples.log",
        script:
            script_path("fig02__coherence_waveform_examples.py")


rule fig03__combined_sketch:
    input:
        along="paper/figures/fig03a__sketch__along-track-plane.png",
        across="paper/figures/fig03b__sketch__across-track-plane.png",
    output:
        "paper/figures/fig03__geometry_sketch.png",
    params:
        fs=120,
        pos="+40+40",
        pad=500,
    log:
        "<logs>/fig03__combined_sketch.log",
    shell:
        r"""
        FONT=$(fc-match -f '%{{file}}\n' 'DejaVu Sans:style=Bold')
        echo "Found font at file: $FONT" > {log}
        SPEC="-gravity northwest -font $FONT -pointsize {params.fs} -annotate {params.pos}"
        echo "Full font specifier:\n$SPEC" >> {log}
        magick \
            \( {input.along} -resize x95% $SPEC a \) \
            \( {input.across} $SPEC b \) \
            +smush {params.pad} {output} >> {log} 2>&1
        """


rule subregion_area_totals_from_RGI:
    input:
        ancient("<resources>/auxiliary/RGI/RGI2000-v7.0-G-global-attributes.csv"),
        ancient(
            "<resources>/auxiliary/RGI/RGI2000-v7.0-G-05_greenland_periphery/RGI2000-v7.0-G-05_greenland_periphery.shp"
        ),
    output:
        "<resources>/subregion_area_totals_from_RGI.pkl",
    log:
        "<logs>/subregion_area_totals_from_RGI.log",
    script:
        script_path("subregion_area_totals_from_RGI.py")


if PUBLICATION_ARTIFACT_SOURCE == "produced":

    rule tabA2__subregion_overview:
        input:
            trends=TREND_RASTERS,
            rgi_o1=ancient(RGI_O1_REGIONS),
            rgi_o2=ancient(RGI_O2_REGIONS),
            glaciers=ancient(
                expand(
                    "<resources>/auxiliary/RGI/RGI2000-v7.0-G-{token}/RGI2000-v7.0-G-{token}.shp",
                    token=rgi_shapefile_tokens,
                )
            ),
            o2_areas_rgi="<resources>/subregion_area_totals_from_RGI.pkl",
        output:
            "<results>/tabA2__subregion_overview.tex",
        params:
            trend_root=pathvar_path("<resources>/trends_dataset"),
        log:
            "<logs>/tabA2__subregion_overview.log",
        script:
            script_path("tabA2__subregion_overview.py")


if GLACIERIZED_AREA_SOURCE == "produced":

    rule glacierized_areas:
        input:
            TREND_RASTERS,
            rgi_o1=ancient(RGI_O1_REGIONS),
            rgi_o2=ancient(RGI_O2_REGIONS),
        output:
            CURRENT_SOURCE_AREA_TABLE,
        params:
            trend_root=pathvar_path("<resources>/trends_dataset"),
        log:
            "<logs>/glacierized_areas.log",
        script:
            script_path("measure_glacierized_areas.py")


if PUBLICATION_ARTIFACT_SOURCE == "produced":

    rule figA3__vavilov_feature:
        input:
            trend=local_trend_path("Russian_Arctic__Severnaya_Zemlya"),
            outline=ancient(
                "<resources>/auxiliary/RGI/RGI2000-v7.0-C-09_russian_arctic/RGI2000-v7.0-C-09_russian_arctic.shp"
            ),
            monthly_ds=ancient(
                "<resources>/monthly_dataset/Glacier_surface_elevation__Russian_Arctic__Severnaya_Zemlya__monthly_500x500m.nc"
            ),
        output:
            "paper/figures/figA3__vavilov_feature.pdf",
        log:
            "<logs>/figA3__vavilov_feature.log",
        script:
            script_path("figA3__vavilov_feature.py")


if CALVAL_SOURCE == "produced":

    rule calval__select_arcticdem_strips:
        input:
            rgi_o1=ancient(RGI_O1_REGIONS),
            glaciers=ancient(
                "<resources>/auxiliary/RGI/RGI2000-v7.0-G-{token}/RGI2000-v7.0-G-{token}.shp"
            ),
        output:
            "<resources>/calval/select_arcticdem_strips__{token}.lock.feather",
            "<resources>/calval/select_arcticdem_strips__{token}.png",
        log:
            "<logs>/calval/select_arcticdem_strips__{token}.log",
        script:
            script_path("calval__select_arcticdem_strips.py")


    rule calval__download_arcticdem_strips:
        input:
            "<resources>/calval/select_arcticdem_strips__{token}.lock.feather",
            rgi_o1=ancient(RGI_O1_REGIONS),
        output:
            "<resources>/calval/download_arcticdem_strips__{token}.done",
        threads: 4
        log:
            "<logs>/calval/download_arcticdem_strips__{token}.log",
        script:
            script_path("calval__download_arcticdem_strips.py")

    def list_regions(wc):
        o1 = int(wc.token[1])
        region = strip_spec_chars(rgi_names[o1]["name"])
        return [
            f"{region}__{strip_spec_chars(rgi_names[o1][o2])}"
            for o2 in rgi_names[o1].keys()
            if o2 not in ["name", "long_code"]
        ]
        
    rule calval__compare_arcticdem_strips:
        input:
            ancient("<resources>/calval/select_arcticdem_strips__{token}.lock.feather"),
            ancient(
                expand(
                    "<resources>/monthly_dataset/Glacier_surface_elevation__{reg}__monthly_500x500m.nc",
                    reg=list_regions,
                )
            ),
            "<resources>/calval/download_arcticdem_strips__{token}.done",
        output:
            calval_compare_path("interpolation_type", "{token}"),
            calval_compare_path("temporal_correlation", "{token}"),
        threads: 4
        log:
            notebook="<logs>/calval/compare_arcticdem_strips__{token}.ipynb",
        benchmark:
            "<logs>/calval/compare_arcticdem_strips__{token}.benchmarks.txt"
        notebook:
            notebook_path("calval__compare_arcticdem_strips.py.ipynb")


DOWNLOADED_ANALYSIS_OUTPUTS = []
if GLACIERIZED_AREA_SOURCE == "downloaded":
    DOWNLOADED_ANALYSIS_OUTPUTS.append(CURRENT_SOURCE_AREA_TABLE)
if ELEVATION_TIMESERIES_SOURCE == "downloaded":
    DOWNLOADED_ANALYSIS_OUTPUTS.append(CURRENT_SOURCE_AVG_TABLE)
if CALVAL_SOURCE == "downloaded":
    DOWNLOADED_ANALYSIS_OUTPUTS.extend(CURRENT_SOURCE_CALVAL_INTERPOLATION)
    DOWNLOADED_ANALYSIS_OUTPUTS.extend(CURRENT_SOURCE_CALVAL_TEMPORAL)
if COVERAGE_ANALYSIS_SOURCE == "downloaded":
    DOWNLOADED_ANALYSIS_OUTPUTS.append(CURRENT_SOURCE_COVERAGE_ANALYSIS)


if DOWNLOADED_ANALYSIS_OUTPUTS:

    rule download_analysis_data:
        output:
            DOWNLOADED_ANALYSIS_OUTPUTS,
        params:
            archive=pathvar_path("<resources>/downloads/downloaded_publication_data.zip"),
            url=PUBLICATION_DATA_URL,
        log:
            "<logs>/download_analysis_data.log",
        run:
            download_archive_members(
                url=params.url,
                archive_path=params.archive,
                destinations=list(output),
                log_path=log[0],
            )


if PUBLICATION_ARTIFACT_SOURCE == "downloaded":

    rule download_publication_artifacts:
        output:
            PUBLICATION_ARCHIVED_OUTPUTS,
        params:
            archive=pathvar_path("<resources>/downloads/publication_artifacts.zip"),
            url=PUBLICATION_DATA_URL,
        log:
            "<logs>/download_publication_artifacts.log",
        run:
            download_archive_members(
                url=params.url,
                archive_path=params.archive,
                destinations=list(output),
                log_path=log[0],
            )


rule calval__estimate_interpolation_uncertainty:
    input:
        CURRENT_SOURCE_CALVAL_INTERPOLATION,
    output:
        unc_tbl="<results>/uncertainty_by_interp__uncertainty.csv",
        corr_tbl="<results>/uncertainty_by_interp__correlations.csv",
        interp_bias_fig="paper/figures/figA1__bias_by_interp_type.pdf",
    log:
        notebook="<logs>/calval/estimate_interpolation_uncertainty.ipynb",
    benchmark:
        "<logs>/calval/estimate_interpolation_uncertainty.benchmarks.txt"
    notebook:
        notebook_path("calval__estimate_interpolation_uncertainty.py.ipynb")


rule calval__estimate_temporal_error_correlation:
    input:
        CURRENT_SOURCE_CALVAL_TEMPORAL,
    output:
        "<results>/one_year_error_correlation.txt",
        boxen_plt="paper/figures/figA2__one_year_error_correlation.pdf",
    log:
        notebook="<logs>/calval/estimate_temporal_error_correlation.ipynb",
    benchmark:
        "<logs>/calval/estimate_temporal_error_correlation.benchmarks.txt"
    notebook:
        notebook_path("calval__estimate_temporal_error_correlation.py.ipynb")


rule calval_all:
    input:
        "<results>/uncertainty_by_interp__uncertainty.csv",
        "<results>/uncertainty_by_interp__correlations.csv",
        "<results>/one_year_error_correlation.txt",
        "paper/figures/figA1__bias_by_interp_type.pdf",
        "paper/figures/figA2__one_year_error_correlation.pdf",


if ELEVATION_TIMESERIES_SOURCE == "produced":

    rule retrieve_elevation_timeseries:
        input:
            monthly=ancient(
                expand(
                    "<resources>/monthly_dataset/Glacier_surface_elevation__{token}__monthly_500x500m.nc",
                    token=filename_tokens,
                )
            ),
            unc_tbl="<results>/uncertainty_by_interp__uncertainty.csv",
            corr_tbl="<results>/uncertainty_by_interp__correlations.csv",
            rgi_o1=ancient(RGI_O1_REGIONS),
            rgi_o2=ancient(RGI_O2_REGIONS),
        output:
            CURRENT_SOURCE_AVG_TABLE,
        log:
            "<logs>/retrieve_elevation_timeseries.log",
        script:
            script_path("retrieve_elevation_timeseries.py")


if PUBLICATION_ARTIFACT_SOURCE == "produced":

    rule result__value_collection:
        input:
            area_rgi="<resources>/subregion_area_totals_from_RGI.pkl",
            area_tbl=CURRENT_SOURCE_AREA_TABLE,
            rgi_attrs=ancient("<resources>/auxiliary/RGI/RGI2000-v7.0-G-global-attributes.csv"),
            avg_elev_tbl=CURRENT_SOURCE_AVG_TABLE,
            yr1_corr="<results>/one_year_error_correlation.txt",
            omitted_tbl="<results>/omitted_subregions.csv",
        output:
            "<logs>/result__value_collection.ipynb",
            subregion_trend_table="<results>/tab01__subregion_trend_table.tex",
            value_collection="<results>/result__value_collection.yaml",
            trend_tbl="<results>/result__regional_trends.csv",
            grnl_tbl="<results>/result__greenland_trends.csv",
            period_p_values="<results>/result__period_comparison_p_values.csv",
        log:
            notebook="<logs>/result__value_collection.ipynb",
        benchmark:
            "<logs>/result__value_collection.benchmarks.txt"
        notebook:
            notebook_path("result__value_collection.py.ipynb")


rule fig04__arcticwide_timeseries:
    input:
        area_tbl=CURRENT_SOURCE_AREA_TABLE,
        avg_elev_tbl=CURRENT_SOURCE_AVG_TABLE,
    output:
        "paper/figures/fig04__arctic-wide_time_series.pdf",
    log:
        "<logs>/fig04__arcticwide_timeseries.log",
    script:
        script_path("fig04__arctic-wide_time_series.py")


rule fig05__regional_time_series:
    input:
        area_tbl=CURRENT_SOURCE_AREA_TABLE,
        avg_elev_tbl=CURRENT_SOURCE_AVG_TABLE,
        rgi_o1=ancient(RGI_O1_REGIONS),
    output:
        "paper/figures/fig05__regional_time_series.pdf",
    log:
        "<logs>/fig05__regional_time_series.log",
    script:
        script_path("fig05__regional_time_series.py")


ICECAP_REGIONS = {
    "barnes": (
        4,
        [
            "West Baffin Island",
            "East Central Baffin Island",
        ],
    ),
    "penny": (
        4,
        [
            "South East Baffin Island",
            "Cumberland Sound",
        ],
    ),
    "sukkerqara": (5, ["South West Greenland"]),
    "scandinavian": (
        8,
        [
            "North Scandinavia",
            "Southwest Scandinavia",
            "Southeast Scandinavia",
        ],
    ),
    "Iceland": (6, ["Iceland"]),
}


def rgi_shp_path(o1: int, C_or_G):
    return (
        f'<resources>/auxiliary/RGI/RGI2000-v7.0-{C_or_G}-{rgi_names[o1]["long_code"]}'
        f'/RGI2000-v7.0-{C_or_G}-{rgi_names[o1]["long_code"]}.shp'
    )


def icecap_inputs(wc):
    o1, _subregion_list = ICECAP_REGIONS[wc.token]
    regions = [
        strip_spec_chars(f"{rgi_names[o1]["name"]}  {sr}")
        for sr in _subregion_list
    ]
    return [
        *expand(
            "<resources>/monthly_dataset/Glacier_surface_elevation__{region}__monthly_500x500m.nc",
            region=regions,
        ),
        rgi_shp_path(o1, "C"),
    ]


if PUBLICATION_ARTIFACT_SOURCE == "produced":

    rule closeup__icecap:
        input:
            ancient(icecap_inputs),
            unc_tbl="<results>/uncertainty_by_interp__uncertainty.csv",
            corr_tbl="<results>/uncertainty_by_interp__correlations.csv",
        output:
            "<results>/closeup__icecap__{token}.yaml",
        threads: 4
        log:
            notebook="<logs>/closeup__icecap__{token}.ipynb",
        benchmark:
            "<logs>/closeup__icecap__{token}.benchmarks.txt"
        notebook:
            notebook_path("closeup__icecap.py.ipynb")


glacier_name_rgi_id_dict = {
    "Vatnajökull": "RGI2000-v7.0-C-06-00209",
}


rule subset_monthly_dataset:
    input:
        ancient(icecap_inputs),
    output:
        "<resources>/monthly_dataset/Glacier_surface_elevation__{token}__{subregion}__{glacier_name}__{period}__monthly_500x500m.nc",
    params:
        glacier_rgi_id=lambda wc: glacier_name_rgi_id_dict[wc.glacier_name]
    threads:
        4
    log:
        "<logs>/subset_monthly_dataset__{token}__{subregion}__{glacier_name}__{period}.log",
    benchmark:
        "<logs>/subset_monthly_dataset__{token}__{subregion}__{glacier_name}__{period}.benchmarks.txt",
    script:
        script_path("subset_monthly_dataset.py")


rule iceland_vatnajokull_trend_from_monthly_ds:
    input:
        nc="<resources>/monthly_dataset/Glacier_surface_elevation__Iceland__Iceland__Vatnajökull__2010-2019__monthly_500x500m.nc",
        rgi=ancient(rgi_shp_path(6, "G")),
    output:
        "<resources>/trends_dataset/Glacier_surface_elevation_trend_2010-2019__Iceland__Iceland__Vatnajökull__500x500m.tif",
    threads: 4
    log:
        "<logs>/iceland_vatnajokull_trend_from_monthly_ds.log",
    benchmark:
        "<logs>/iceland_vatnajokull_trend_from_monthly_ds.benchmarks.txt"
    shell:
        f'python {script_path("build_trend_georaster.py")} {{input.nc}} {{output}} --non-interactive'


REF_SENTINEL = "N64W018_2010-01-01_2020-01-01_dhdt.tif"


rule download_iceland_hugonnet_tiles:
    output:
        temp(directory("<resources>/reference_trends/dhdt")),
        temp(directory("<resources>/reference_trends/dhdt_err")),
        sentinel=temp(f"<resources>/reference_trends/dhdt/{REF_SENTINEL}"),
    log:
        "<logs>/download_iceland_hugonnet_tiles.log",
    script:
        script_path("download_iceland_hugonnet_tiles.py")


rule align_ref_trends:
    input:
        "<resources>/reference_trends/dhdt",
        ref_sentinel=f"<resources>/reference_trends/dhdt/{REF_SENTINEL}",
        own="<resources>/trends_dataset/Glacier_surface_elevation_trend_2010-2019__Iceland__Iceland__Vatnajökull__500x500m.tif",
    output:
        "<resources>/reference_trends/ref_trends_Vatnajökull.tif",
    log:
        "<logs>/align_ref_trends.log",
    script:
        script_path("align_ref_trends.py")


if PUBLICATION_ARTIFACT_SOURCE == "produced":

    rule iceland_hugonnet_comparison:
        input:
            basins="<resources>/auxiliary/RGI/RGI2000-v7.0-G-06_iceland/RGI2000-v7.0-G-06_iceland.shp",
            cmplxs="<resources>/auxiliary/RGI/RGI2000-v7.0-C-06_iceland/RGI2000-v7.0-C-06_iceland.shp",
            ref="<resources>/reference_trends/ref_trends_Vatnajökull.tif",
            own="<resources>/trends_dataset/Glacier_surface_elevation_trend_2010-2019__Iceland__Iceland__Vatnajökull__500x500m.tif",
        output:
            diff_raster="<results>/fig14c_source__trend_diff_to_ref.tif",
            vals="<results>/vatna_deviation_analysis.yaml",
            expl_tbl="<results>/vatna_deviation_analysis.csv",
            fig15="paper/figures/fig15__vatna_hugonnet_stat_comparison.pdf",
        log:
            notebook="<logs>/iceland_hugonnet_comparison.ipynb",
        benchmark:
            "<logs>/iceland_hugonnet_comparison.benchmarks.txt"
        notebook:
            notebook_path("iceland_hugonnet_comparison.py.ipynb")


rule arcticdem_mosaic_100m:
    output:
        "<resources>/auxiliary/DEM/arcticdem_mosaic_100m_v4.1_dem.tif",
    log:
        "<logs>/arcticdem_mosaic_100m.log",
    benchmark:
        "<logs>/arcticdem_mosaic_100m.benchmarks.txt",
    shell:
        """
        archive=$TMP"/arcticdem_mosaic_100m_v4.1.tar.gz"
        aria2c -c -x 8 -s 8 -k 1M \
            --summary-interval 60 \
            --show-console-readout false \
            --dir /tmp \
            --out "$(basename "$archive")" \
            https://data.pgc.umn.edu/elev/dem/setsm/ArcticDEM/mosaic/v4.1/100m/arcticdem_mosaic_100m_v4.1.tar.gz \
            &> {log}
        tmp_tif="$TMP/arcticdem_mosaic_100m_v4.1_dem.tif.tmp"
        tar -xOzf "$archive" "arcticdem_mosaic_100m_v4.1_dem.tif" >| "$tmp_tif" 2>> "{log}"
        mv "$tmp_tif" {output}
        """


if COVERAGE_ANALYSIS_SOURCE == "produced":

    rule coverage_analysis:
        input:
            TREND_RASTERS,
            dem=ancient("<resources>/auxiliary/DEM/arcticdem_mosaic_100m_v4.1_dem.tif"),
        output:
            CURRENT_SOURCE_COVERAGE_ANALYSIS,
        threads:
            24
        log:
            "<logs>/coverage_analysis.log",
        benchmark:
            "<logs>/coverage_analysis.benchmarks.txt",
        script:
            script_path("coverage_analysis.py")


rule fig16__coverage_terraincomplexity_correlation:
    input:
        CURRENT_SOURCE_COVERAGE_ANALYSIS,
    output:
        fig="paper/figures/fig16__coverage_terraincomplexity_correlation.pdf",
        fit="<results>/coverage_terraincomplexity_correlation.yaml",
    log:
        "<logs>/fig16__coverage_terraincomplexity_correlation.log",
    script:
        script_path("fig16__coverage_terraincomplexity_correlation.py")


if PUBLICATION_ARTIFACT_SOURCE == "produced":

    rule omitted_subregions:
        input:
            ancient("<resources>/auxiliary/RGI/RGI2000-v7.0-G-global-attributes.csv"),
            rgi_o2=ancient(RGI_O2_REGIONS),
        output:
            "<results>/omitted_subregions.csv",
        log:
            "<logs>/omitted_subregions.log",
        script:
            script_path("omitted_subregions.py")


rule tab03__JG_comparison:
    input:
        "<results>/result__regional_trends.csv",
    output:
        "<results>/tab03__JG_comparison.tex",
    log:
        "<logs>/tab03__JG_comparison.log",
    script:
        script_path("tab03__JG_comparison.py")


rule materialize_manuscript_tex:
    input:
        template="paper/paper__template.tex.j2",
        value_collection="<results>/result__value_collection.yaml",
        o1_trend_tbl="<results>/tab01__subregion_trend_table.tex",
        refJG_tbl="<results>/tab03__JG_comparison.tex",
        one_yr_corr="<results>/one_year_error_correlation.txt",
        barnes="<results>/closeup__icecap__barnes.yaml",
        penny="<results>/closeup__icecap__penny.yaml",
        sukkerqara="<results>/closeup__icecap__sukkerqara.yaml",
        scandinavian="<results>/closeup__icecap__scandinavian.yaml",
        fig16_clip="<results>/vatna_deviation_analysis.yaml",
        cover_fit="<results>/coverage_terraincomplexity_correlation.yaml",
        subreg_tbl="<results>/tabA2__subregion_overview.tex",
        omitted="<results>/omitted_subregions.csv",
        trend_tbl="<results>/result__regional_trends.csv",
        grnl_tbl="<results>/result__greenland_trends.csv",
        isl_disc="<results>/vatna_deviation_analysis.csv",
        cov_disc="<results>/coverage_analysis.csv",
        period_p_values="<results>/result__period_comparison_p_values.csv",
    output:
        "paper/manuscript.tex",
    log:
        "<logs>/render_paper.log",
    script:
        script_path("materialize_paper.py")


rule copernicus_latex_template:
    output:
        bst="paper/copernicus.bst",
        cfg="paper/copernicus.cfg",
        cls="paper/copernicus.cls",
    params:
        url=COPERNICUS_LATEX_TEMPLATE_URL,
        target="paper",
    log:
        "<logs>/copernicus_latex_template.log",
    shell:
        """
        c="copernicus"
        tmp="$TMP"/"$c"_template.zip
        wget -O $tmp \
            -e robots=off \
            "{params.url}" > {log} 2>&1
        unzip -o $tmp $c.bst $c.cfg $c.cls -d {params.target} >> {log} 2>&1
        rm $tmp
        """


rule compile_manuscript_pdf:
    input:
        tex="paper/manuscript.tex",
        bbl=ancient("paper/manuscript.bbl"),
        bst=ancient("paper/copernicus.bst"),
        cfg=ancient("paper/copernicus.cfg"),
        cls=ancient("paper/copernicus.cls"),
        generated_figures=MANUSCRIPT_GENERATED_FIGURES,
        external_figures=MANUSCRIPT_EXTERNAL_FIGURES,
    output:
        "paper/manuscript.pdf",
    params:
        path="paper",
    log:
        "<logs>/compile_manuscript_pdf.log",
    shell:
        "cd {params.path} && pdflatex {input.tex} && pdflatex {input.tex}"
