#!/usr/bin/env python3
"""Generate the selector-aware Snakemake rule graph used in the README."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import html
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "workflow-source-selectors.svg"
TARGET = "publication_reproduction"
SIGNATURE_RE = re.compile(r"workflow-diagram-source-sha256: ([0-9a-f]{64})")


@dataclass(frozen=True)
class Selector:
    name: str
    short_label: str
    color: str
    fill: str
    replacement_rule: str


SELECTORS = (
    Selector(
        "calval_source",
        "cal/val",
        "#E69F00",
        "#FCE8BA",
        "download_analysis_data",
    ),
    Selector(
        "coverage_analysis_source",
        "coverage",
        "#56B4E9",
        "#D9F0FA",
        "download_analysis_data",
    ),
    Selector(
        "glacierized_area_source",
        "area",
        "#009E73",
        "#D7EFE8",
        "download_analysis_data",
    ),
    Selector(
        "elevation_timeseries_source",
        "elevation",
        "#CC79A7",
        "#F3E2EF",
        "download_analysis_data",
    ),
    Selector(
        "publication_artifact_source",
        "publication artifacts",
        "#D55E00",
        "#F8DCD5",
        "download_publication_artifacts",
    ),
)


@dataclass(frozen=True)
class RuleGraph:
    nodes: frozenset[str]
    edges: frozenset[tuple[str, str]]


NODE_RE = re.compile(r'^\s*(\d+)\[label = "([^"]+)",')
EDGE_RE = re.compile(r"^\s*(\d+) -> (\d+)")


def parse_rulegraph(dot: str) -> RuleGraph:
    """Parse the deliberately simple DOT emitted by Snakemake --rulegraph."""
    nodes_by_id: dict[str, str] = {}
    raw_edges: list[tuple[str, str]] = []

    for line in dot.splitlines():
        if match := NODE_RE.match(line):
            node_id, rule_name = match.groups()
            nodes_by_id[node_id] = rule_name
        elif match := EDGE_RE.match(line):
            raw_edges.append(match.groups())

    if not nodes_by_id:
        raise RuntimeError("Snakemake returned no rule-graph nodes")
    if len(nodes_by_id.values()) != len(set(nodes_by_id.values())):
        raise RuntimeError("Snakemake rule graph contains duplicate rule labels")

    try:
        edges = {
            (nodes_by_id[source], nodes_by_id[target])
            for source, target in raw_edges
        }
    except KeyError as error:
        raise RuntimeError(
            f"Rule-graph edge references unknown node {error}"
        ) from error

    return RuleGraph(frozenset(nodes_by_id.values()), frozenset(edges))


def evaluate_rulegraph(
    selector_values: dict[str, str], runtime_cache: Path
) -> RuleGraph:
    config_args = [
        f"{selector.name}={selector_values[selector.name]}" for selector in SELECTORS
    ]
    command = [
        sys.executable,
        "-m",
        "snakemake",
        "--rulegraph",
        "dot",
        TARGET,
        "--cores",
        "1",
        "--nolock",
        "--runtime-source-cache-path",
        str(runtime_cache),
        "--config",
        *config_args,
    ]
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(
            "Snakemake could not generate the rule graph:\n" + result.stderr.strip()
        )
    return parse_rulegraph(result.stdout)


def evaluate_variants() -> tuple[RuleGraph, dict[str, RuleGraph]]:
    produced = {selector.name: "produced" for selector in SELECTORS}
    with tempfile.TemporaryDirectory(prefix="workflow-diagram-cache-") as cache:
        configs = {
            "all_produced": produced,
            **{
                selector.name: {**produced, selector.name: "downloaded"}
                for selector in SELECTORS
            },
        }

        def evaluate(item: tuple[str, dict[str, str]]) -> tuple[str, RuleGraph]:
            name, values = item
            runtime_cache = Path(cache, name)
            runtime_cache.mkdir()
            return name, evaluate_rulegraph(values, runtime_cache)

        with ThreadPoolExecutor(max_workers=len(configs)) as executor:
            graphs = dict(executor.map(evaluate, configs.items()))

        baseline = graphs.pop("all_produced")
        variants = graphs
    return baseline, variants


def dot_quote(value: str) -> str:
    # Backslashes are left intact so Graphviz escapes such as ``\n`` retain
    # their meaning. Rule and selector names cannot contain arbitrary input.
    return '"' + value.replace('"', '\\"') + '"'


def rule_label(rule: str) -> str:
    return rule.replace("__", "__\\n")


def selector_colors(names: tuple[str, ...]) -> str:
    colors = [selector.color for selector in SELECTORS if selector.name in names]
    return ":".join(colors)


def selector_labels(names: tuple[str, ...]) -> str:
    labels = [selector.short_label for selector in SELECTORS if selector.name in names]
    return " / ".join(labels)


def build_annotated_dot(baseline: RuleGraph, variants: dict[str, RuleGraph]) -> str:
    if TARGET not in baseline.nodes:
        raise RuntimeError(f"Baseline graph does not contain target rule {TARGET}")

    bypassed_by = {
        rule: tuple(
            selector.name
            for selector in SELECTORS
            if rule not in variants[selector.name].nodes
        )
        for rule in baseline.nodes
    }
    for selector in SELECTORS:
        bypassed = baseline.nodes - variants[selector.name].nodes
        if not bypassed:
            raise RuntimeError(
                f"{selector.name}=downloaded does not bypass any produced rules"
            )
        if selector.replacement_rule not in variants[selector.name].nodes:
            raise RuntimeError(
                f"{selector.name}=downloaded does not activate "
                f"{selector.replacement_rule}"
            )

    all_nodes = set(baseline.nodes)
    all_edges = set(baseline.edges)
    for graph in variants.values():
        all_nodes.update(graph.nodes)
        all_edges.update(graph.edges)

    edge_owners = {
        edge: tuple(
            selector.name
            for selector in SELECTORS
            if edge in variants[selector.name].edges and edge not in baseline.edges
        )
        for edge in all_edges - baseline.edges
    }

    lines = [
        "digraph selector_aware_workflow {",
        '  graph [rankdir=LR, bgcolor="white", pad=0.2, nodesep=0.35, ranksep=0.8,',
        '         splines=spline, fontname="sans", labelloc=t,',
        '         label="publication_reproduction: produced paths and '
        'downloaded bypasses"];',
        '  node [shape=box, style="rounded,filled", fontname="monospace",',
        '        fontsize=9, color="#6B7280", fillcolor="#F3F4F6", '
        'penwidth=1.4, margin="0.12,0.08"];',
        '  edge [fontname="sans", fontsize=8, color="#9CA3AF", '
        'penwidth=1.4, arrowsize=0.7];',
    ]

    clustered: set[str] = set()
    for selector in SELECTORS:
        members = sorted(
            rule
            for rule, owners in bypassed_by.items()
            if owners == (selector.name,)
        )
        if not members:
            continue
        lines.extend(
            [
                f"  subgraph cluster_{selector.name} {{",
                "    label="
                f"{dot_quote(selector.name + '=downloaded bypasses these rules')};",
                f'    color="{selector.color}"; fontcolor="{selector.color}";',
                '    style="rounded,dashed"; penwidth=2; margin=12;',
            ]
        )
        for rule in members:
            lines.append(
                f"    {dot_quote(rule)} [label={dot_quote(rule_label(rule))}, "
                f'color="{selector.color}", fillcolor="{selector.fill}"];'
            )
            clustered.add(rule)
        lines.append("  }")

    for rule, owners in sorted(bypassed_by.items()):
        if rule in clustered:
            continue
        attributes = [f"label={dot_quote(rule_label(rule))}"]
        if owners:
            owner_fills = ":".join(
                selector.fill for selector in SELECTORS if selector.name in owners
            )
            attributes.extend(
                [
                    'style="rounded,striped"',
                    f'fillcolor="{owner_fills}"',
                    f'xlabel={dot_quote("bypassed by " + selector_labels(owners))}',
                ]
            )
        if rule == TARGET:
            attributes.extend(
                ['shape="doubleoctagon"', 'fillcolor="#E5E7EB"', 'penwidth=2']
            )
        lines.append(f"  {dot_quote(rule)} [{', '.join(attributes)}];")

    download_nodes = sorted(all_nodes - baseline.nodes)
    for rule in download_nodes:
        if rule == "download_analysis_data":
            annotation = "shared by four analysis selectors"
        elif rule == "download_publication_artifacts":
            annotation = "publication_artifact_source=downloaded"
        else:
            annotation = "downloaded replacement"
        label = f"{rule}\\n({annotation})"
        lines.append(
            f"  {dot_quote(rule)} [label={dot_quote(label)}, shape=box, "
            'peripheries=2, style="rounded,filled,bold", color="#374151", '
            'fillcolor="#FFF7D6", penwidth=1.8];'
        )

    for source, target in sorted(baseline.edges):
        lines.append(f"  {dot_quote(source)} -> {dot_quote(target)};")

    for edge in sorted(all_edges - baseline.edges):
        owners = edge_owners[edge]
        if not owners:
            raise RuntimeError(f"Downloaded-only edge has no selector owner: {edge}")
        source, target = edge
        colors = selector_colors(owners)
        label = dot_quote(selector_labels(owners) + " downloaded")
        lines.append(
            f"  {dot_quote(source)} -> {dot_quote(target)} "
            f'[color="{colors}", fontcolor="{colors.split(":")[0]}", '
            f"style=dashed, penwidth=2.6, label={label}];"
        )

    legend_rows = [
        '<TR><TD COLSPAN="2"><B>Selector legend</B></TD></TR>',
        *[
            f'<TR><TD BGCOLOR="{selector.fill}"> </TD>'
            f'<TD ALIGN="LEFT"><FONT COLOR="{selector.color}">'
            f'{html.escape(selector.name)}=downloaded</FONT></TD></TR>'
            for selector in SELECTORS
        ],
        '<TR><TD BORDER="2" BGCOLOR="#FFF7D6"> </TD>'
        '<TD ALIGN="LEFT">download replacement rule</TD></TR>',
        '<TR><TD BGCOLOR="#F3F4F6"> </TD>'
        '<TD ALIGN="LEFT">rule retained in all selector variants</TD></TR>',
    ]
    legend = "".join(legend_rows)
    lines.append(
        '  "selector_legend" [shape=plain, fontname="sans", label=<<TABLE BORDER="1" '
        f'CELLBORDER="1" CELLSPACING="0" CELLPADDING="5">{legend}</TABLE>>];'
    )
    lines.append(f'  {{ rank=sink; {dot_quote(TARGET)}; "selector_legend"; }}')
    lines.append("}")
    return "\n".join(lines) + "\n"


def source_signature(dot: str) -> str:
    return hashlib.sha256(dot.encode("utf-8")).hexdigest()


def validate_svg(svg: str) -> None:
    try:
        ET.fromstring(svg)
    except ET.ParseError as error:
        raise RuntimeError(f"Graphviz returned invalid SVG: {error}") from error


def render_svg(dot: str) -> str:
    result = subprocess.run(
        ["dot", "-Tsvg"],
        cwd=REPO_ROOT,
        input=dot,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError("Graphviz could not render the diagram:\n" + result.stderr)
    signature = source_signature(dot)
    svg = result.stdout.replace(
        "<svg ",
        f"<!-- workflow-diagram-source-sha256: {signature} -->\n<svg ",
        1,
    )
    validate_svg(svg)
    return svg


def check_output(output: Path, dot: str) -> int:
    if not output.exists():
        print(
            f"Workflow diagram is missing: {output.relative_to(REPO_ROOT)}",
            file=sys.stderr,
        )
        return 1
    svg = output.read_text(encoding="utf-8")
    validate_svg(svg)
    match = SIGNATURE_RE.search(svg)
    expected = source_signature(dot)
    if not match or match.group(1) != expected:
        print(
            "Workflow diagram is stale. Run `pixi run workflow-diagram`.",
            file=sys.stderr,
        )
        return 1
    print(f"Workflow diagram is up to date: {output.relative_to(REPO_ROOT)}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed SVG does not match the current workflow topology",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    baseline, variants = evaluate_variants()
    dot = build_annotated_dot(baseline, variants)
    if args.check:
        return check_output(DEFAULT_OUTPUT, dot)

    svg = render_svg(dot)
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT.write_text(svg, encoding="utf-8")
    print(f"Wrote {DEFAULT_OUTPUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
