"""Compare domestic-affiliation coauthorship on OpenAlex physics articles, 2015–2024."""
import argparse
import csv
import gzip
import json
import math
import os
import platform
import random
import re
import time
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

import igraph as ig
import networkx as nx

ROOT = Path(__file__).resolve().parent
API = "https://api.openalex.org/works"
FIELD_URL = "https://openalex.org/fields/31"
FIELD_NAME = "Physics and Astronomy"
SELECT = "id,doi,title,publication_year,type,primary_topic,authorships,is_authors_truncated"
YEARS = range(2015, 2025)
PERIODS = ((2015, 2019), (2020, 2024))
CUTOFFS = (20, 50, 100)
PER_PAGE = 100
LOUVAIN_SEEDS = (42, 43, 44)
UNKNOWN_AUTHORS = {"A9999999999", "A5317838346"}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def request_json(url):
    headers = {"User-Agent": "Iran-Physics-Coauthorship/2.0", "Accept-Encoding": "gzip"}
    key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if key:
        headers["Authorization"] = "Bearer " + key
    for attempt in range(5):
        try:
            with urlopen(Request(url, headers=headers), timeout=75) as response:
                data = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return json.loads(data)
        except HTTPError as exc:
            body = exc.read(800).decode(errors="replace")
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 4 or "daily_budget" in body:
                raise RuntimeError(f"OpenAlex HTTP {exc.code}: {body}") from exc
            try:
                wait = max(float(exc.headers.get("Retry-After") or 0), 2 ** attempt)
            except ValueError:
                wait = 2 ** attempt
            if wait > 90:
                raise RuntimeError("OpenAlex requested a longer pause. The saved pages can be reused.") from exc
            time.sleep(wait)
        except (TimeoutError, URLError, ConnectionError) as exc:
            if attempt == 4:
                raise RuntimeError("OpenAlex could not be reached. The saved pages can be reused.") from exc
            time.sleep(2 ** attempt)


def verify_field(field):
    require(isinstance(field, dict) and field.get("id") == FIELD_URL and
            field.get("display_name") == FIELD_NAME, f"Unexpected OpenAlex field: {field!r}")


def params_for(year, number):
    return {"filter": f"institutions.country_code:IR,primary_topic.field.id:31,type:article,publication_year:{year}",
            "sort": "publication_date:asc", "per_page": str(PER_PAGE), "page": str(number), "select": SELECT}


def verify_page(data, year, number):
    params = params_for(year, number)
    url = urlsplit(data["query_url"])
    require(f"{url.scheme}://{url.netloc}{url.path}" == API and
            parse_qs(url.query) == {k: [v] for k, v in params.items()},
            f"Unrecognized query metadata for year {year}, page {number}")
    meta = data["meta"]
    total = meta["count"]
    require(isinstance(total, int) and 0 <= total <= 10_000,
            f"Cannot page year {year} using basic paging: {total} records")
    require(meta["page"] == number and meta["per_page"] == PER_PAGE, "Page metadata mismatch")
    require(len(data["results"]) == min(PER_PAGE, max(total - PER_PAGE * (number - 1), 0)),
            f"Incomplete page for {year}, page {number}")
    for work in data["results"]:
        verify_field((work.get("primary_topic") or {}).get("field"))
        require(work["publication_year"] == year and work["type"] == "article" and work.get("id"),
                f"Out-of-scope work in {year}, page {number}")
        require(isinstance(work.get("authorships"), list) and
                isinstance(work.get("is_authors_truncated"), bool), "Incomplete authorship metadata")
    return total


def read_page(cache, year, number, offline):
    path = cache / f"{year}-{number:03d}.json.gz"
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as f:
            data = json.load(f)
        verify_page(data, year, number)
    else:
        if offline:
            raise FileNotFoundError(f"Missing OpenAlex page: {path}")
        query_url = API + "?" + urlencode(params_for(year, number))
        data = request_json(query_url)
        data["query_url"] = query_url
        data["retrieved_at_utc"] = timestamp()
        verify_page(data, year, number)
        tmp = path.with_suffix(f".{os.getpid()}.partial")
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=3) as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        tmp.replace(path)
    return data


def compact_work(work):
    authors = {}
    unresolved = 0
    has_ir = False
    for record in work["authorships"]:
        if not any(i.get("country_code") == "IR" for i in record.get("institutions") or []):
            continue
        has_ir = True
        author = record.get("author") or {}
        aid = author.get("id")
        code = (aid or "").rsplit("/", 1)[-1]
        if not re.fullmatch(r"A[1-9][0-9]*", code) or code in UNKNOWN_AUTHORS:
            unresolved += 1
            continue
        authors["https://openalex.org/" + code] = author.get("display_name") or ""
    return (len(work["authorships"]), work["is_authors_truncated"], has_ir, unresolved, authors)


def collect(cache, offline):
    cache.mkdir(parents=True, exist_ok=True)
    field_path = cache / "field_31.json"
    if field_path.exists():
        verify_field(json.loads(field_path.read_text(encoding="utf-8")))
    elif not offline:
        field = request_json("https://api.openalex.org/fields/31")
        verify_field(field)
        tmp = field_path.with_suffix(f".{os.getpid()}.partial")
        tmp.write_text(json.dumps(field), encoding="utf-8")
        tmp.replace(field_path)
    years = {}
    scopes = []
    seen = set()
    for year in YEARS:
        first = read_page(cache, year, 1, offline)
        total = first["meta"]["count"]
        by_year = []
        dates = []
        npages = max(1, math.ceil(total / PER_PAGE))
        for number in range(1, npages + 1):
            data = first if number == 1 else read_page(cache, year, number, offline)
            require(data["meta"]["count"] == total, f"OpenAlex count changed during retrieval for {year}")
            dates.append(data["retrieved_at_utc"])
            for work in data["results"]:
                wid = work["id"]
                require(wid not in seen, f"Duplicate work ID: {wid}")
                seen.add(wid)
                by_year.append(compact_work(work))
        require(len(by_year) == total, f"Incomplete year {year}")
        years[year] = by_year
        scopes.append({"year": year, "unique_works": total, "pages": npages,
                       "retrieved_first_utc": min(dates), "retrieved_last_utc": max(dates),
                       "filter": params_for(year, 1)["filter"]})
        print(f"{year}: {total:,} verified works", flush=True)
    return years, scopes


def build_graph(works, cutoff):
    graph = nx.Graph()
    counts = Counter()
    for count, truncated, has_ir, unresolved, authors in works:
        counts["unique_papers"] += 1
        if truncated:
            counts["excluded_truncated"] += 1
            continue
        if count > cutoff:
            counts["excluded_large_complete_team"] += 1
            continue
        counts["unresolved_ir_authorships_after_team_filter"] += unresolved
        if not has_ir:
            counts["no_identified_ir_institution"] += 1
            continue
        if not authors:
            counts["no_resolved_ir_author_id"] += 1
            continue
        counts["papers_in_network"] += 1
        counts["papers_with_one_ir_author" if len(authors) == 1 else "papers_with_two_plus_ir_authors"] += 1
        for aid, name in sorted(authors.items()):
            if aid not in graph:
                graph.add_node(aid, display_name=name, papers=0)
            graph.nodes[aid]["papers"] += 1
        for u, v in combinations(sorted(authors), 2):
            if graph.has_edge(u, v):
                graph[u][v]["weight"] += 1
            else:
                graph.add_edge(u, v, weight=1)
    return graph, counts


def measure(graph, label, cutoff, counts):
    n = len(graph)
    m = graph.number_of_edges()
    components = sorted(nx.connected_components(graph), key=lambda c: (-len(c), min(c)))
    largest = components[0] if components else set()
    lcc = graph.subgraph(largest)
    partition = []
    modularity = None
    if lcc.number_of_edges():
        # Canonical vertex and edge order keeps the stochastic search reproducible.
        ids = sorted(graph)
        index = {u: i for i, u in enumerate(ids)}
        weighted = sorted((min(index[u], index[v]), max(index[u], index[v]), w)
                          for u, v, w in graph.edges(data="weight"))
        projected = ig.Graph(n=len(ids), edges=[(u, v) for u, v, _ in weighted])
        projected.vs["name"] = ids
        projected.es["weight"] = [w for _, _, w in weighted]
        # Make ties in largest-component selection match the sorted components above.
        connected = projected.induced_subgraph(sorted(index[u] for u in largest))
        try:
            for seed in LOUVAIN_SEEDS:
                ig.set_random_number_generator(random.Random(seed))
                assignment = connected.community_multilevel(weights="weight", resolution=1.0)
                score = assignment.modularity
                if modularity is None or score > modularity:
                    modularity = score
                    partition = [set(connected.vs[group]["name"]) for group in assignment]
        finally:
            ig.set_random_number_generator(None)
    elif largest:
        partition = [largest]
    # Each triangle contributes once to the triangle count at each of its three vertices.
    triangles = nx.triangles(graph)
    wedges = {u: k * (k - 1) // 2 for u, k in graph.degree()}
    triples = sum(wedges.values())
    clustering = sum(triangles[u] / pairs for u, pairs in wedges.items() if pairs)
    repeated = sum(w > 1 for _, _, w in graph.edges(data="weight"))
    names = ("unique_papers", "excluded_truncated", "excluded_large_complete_team",
             "no_identified_ir_institution", "no_resolved_ir_author_id", "papers_in_network",
             "papers_with_one_ir_author", "papers_with_two_plus_ir_authors",
             "unresolved_ir_authorships_after_team_filter")
    row = {"period": label, "max_total_authors": cutoff, **{name: counts[name] for name in names},
           "nodes": n, "edges": m, "edge_weight_sum": sum(w for _, _, w in graph.edges(data="weight")),
           "repeated_edges": repeated, "repeated_edge_share": repeated / m if m else None,
           "mean_degree": 2 * m / n if n else None, "density": nx.density(graph) if n > 1 else None,
           "number_of_components": len(components), "isolates": nx.number_of_isolates(graph),
           "lcc_nodes": len(largest), "lcc_share": len(largest) / n if n else None,
           "mean_local_clustering": clustering / n if n else None,
           "transitivity": sum(triangles.values()) / triples if triples else None,
           "lcc_communities": len(partition), "lcc_weighted_modularity": modularity}
    return row, components, partition


def write_rows(path, keys, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def graph_tables(graph, components, partition, label, out):
    component = {node: index for index, group in enumerate(components, 1) for node in group}
    groups = sorted(partition, key=lambda c: (-len(c), min(c)))
    community = {node: index for index, group in enumerate(groups, 1) for node in group}
    keys = ["author_id", "display_name", "paper_count", "degree", "weighted_degree",
            "component_id", "lcc_community"]
    write_rows(out / f"nodes_{label}.csv", keys,
               (dict(zip(keys, (u, d["display_name"], d["papers"], graph.degree(u),
                               graph.degree(u, weight="weight"), component[u], community.get(u))))
                for u, d in sorted(graph.nodes(data=True))))
    write_rows(out / f"edges_{label}.csv", ["source", "target", "weight"],
               ({"source": min(u, v), "target": max(u, v), "weight": w}
                for u, v, w in graph.edges(data="weight")))
    dist = Counter(dict(graph.degree()).values())
    write_rows(out / f"degree_distribution_{label}.csv", ["degree", "author_count"],
               ({"degree": d, "author_count": count} for d, count in sorted(dist.items())))
    sizes = Counter(map(len, components))
    write_rows(out / f"component_sizes_{label}.csv", ["component_size", "component_count"],
               ({"component_size": size, "component_count": count} for size, count in sorted(sizes.items())))


def degree_plot(out, periods):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    fig, ax = plt.subplots(figsize=(7.1, 4.7))
    drawn = False
    for label in periods:
        with (out / f"degree_distribution_{label}.csv").open() as f:
            dist = {int(r["degree"]): int(r["author_count"]) for r in csv.DictReader(f)}
        denominator = sum(dist.values())
        max_degree = max(dist, default=0)
        if not max_degree:
            continue
        degrees = range(1, max_degree + 1)
        survival = []
        remaining = denominator - dist.get(0, 0)
        for k in degrees:
            survival.append(remaining / denominator)
            remaining -= dist.get(k, 0)
        ax.step(degrees, survival, where="post", label=label)
        drawn = True
    if drawn:
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.legend(frameon=False)
    ax.set(xlabel="Degree (distinct coauthors)", ylabel="Fraction of all authors with degree ≥ k",
           title="Coauthorship degree distribution")
    fig.tight_layout()
    fig.savefig(out / "degree_distribution.png", dpi=180)
    plt.close(fig)
    return True


def output_report(out, rows, manifest, has_plot):
    first, second = rows
    lines = ["# Physics coauthorship among Iran-affiliated authors, 2015–2024", "",
             "Five-year undirected graphs join pairs of authors whose own authorships list an Iranian institution on the same article. Edge weights count shared articles. The primary analysis allows up to 50 total listed authors per article.", "",
             "| Measure | 2015–2019 | 2020–2024 |", "|---|---:|---:|"]
    fields = {"unique_papers": "Articles retrieved", "papers_in_network": "Articles included",
              "nodes": "Distinct authors", "edges": "Distinct coauthor pairs", "mean_degree": "Mean degree",
              "lcc_share": "Fraction in largest component", "repeated_edge_share": "Fraction of pairs with ≥2 articles",
              "mean_local_clustering": "Mean local clustering", "transitivity": "Transitivity",
              "lcc_communities": "Communities on the largest component",
              "lcc_weighted_modularity": "Weighted modularity on the largest component"}
    for key, name in fields.items():
        def display(v):
            return "—" if v is None else (f"{v:.4f}" if isinstance(v, float) else f"{v:,}")
        lines.append(f"| {name} | {display(first[key])} | {display(second[key])} |")
    if has_plot:
        lines.extend(["", "![Degree distribution](degree_distribution.png)"])
    lines.extend(["", "## Interpretation", "",
                  "The corpus comprises OpenAlex articles with primary field 31, Physics and Astronomy, and an institution in Iran. Coverage depends on topic assignment, institutional identification and author disambiguation. Authors with zero eligible neighbors remain in the graph. Unresolved author IDs and incomplete author lists are excluded under the rules in the README.",
                  "", "See `team_size_sensitivity.csv` for thresholds of 20, 50 and 100 total listed authors. Community labels are local to each period. Louvain modularity is descriptive. Comparing its two values cannot establish a statistically significant change in community structure."])
    (out / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "method_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def run(cache, out, offline):
    years, scopes = collect(cache, offline)
    out.mkdir(parents=True, exist_ok=True)
    main_rows, sensitivity = [], []
    for first, last in PERIODS:
        label = f"{first}-{last}"
        works = [work for year in range(first, last + 1) for work in years[year]]
        for cutoff in CUTOFFS:
            graph, counts = build_graph(works, cutoff)
            row, components, partition = measure(graph, label, cutoff, counts)
            sensitivity.append(row)
            if cutoff == 50:
                main_rows.append(row)
                graph_tables(graph, components, partition, label, out)
            print(f"{label}, ≤{cutoff} authors: {row['nodes']:,} nodes and {row['edges']:,} edges", flush=True)
    write_rows(out / "comparison.csv", list(main_rows[0]), main_rows)
    write_rows(out / "team_size_sensitivity.csv", list(sensitivity[0]), sensitivity)
    manifest = {"analysis_at_utc": timestamp(), "source": API, "database": "OpenAlex default core", "field_id": FIELD_URL,
                "field_name": FIELD_NAME, "primary_cutoff_total_authorships": 50, "sensitivity_cutoffs": list(CUTOFFS),
                "selected_fields": SELECT.split(","), "years": scopes, "paging": "100 articles per numbered page within each year, publication_date:asc",
                "nodes": "distinct eligible author IDs from each work, including isolates",
                "excluded_author_ids": sorted(UNKNOWN_AUTHORS),
                "weights": "number of distinct shared articles in each period",
                "community_method": "Louvain on the largest connected component, weight=weight, resolution=1.0",
                "louvain_seeds_highest_q": list(LOUVAIN_SEEDS), "python_version": platform.python_version(),
                "networkx_version": nx.__version__, "igraph_version": ig.__version__}
    output_report(out, main_rows, manifest, degree_plot(out, [row["period"] for row in main_rows]))
    print(f"Outputs: {out.resolve()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=ROOT / "openalex_physics31_pages")
    parser.add_argument("--output", type=Path, default=ROOT / "output_physics31")
    parser.add_argument("--offline", action="store_true", help="Require a complete local page cache")
    args = parser.parse_args()
    run(args.cache, args.output, args.offline)


if __name__ == "__main__":
    main()
