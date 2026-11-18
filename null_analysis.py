"""Test community structure against a year-stratified fixed-margin authorship null.

Input: complete annual OpenAlex list pages from fetch_corpus.py.
Output: observed and randomized graph metrics, comparisons, and method metadata.
Requires python-igraph (installable as igraph). No API credentials are needed.
"""
import argparse
import csv
import gzip
import hashlib
import json
import platform
import random
import re
import statistics
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import igraph as ig


ROOT = Path(__file__).resolve().parent
PERIODS = ((2015, 2019), (2020, 2024))
AUTHOR_ID = re.compile(r"(?:https?://openalex\.org/)?(A[1-9][0-9]*)")
TEAM_CAP = 50
LOUVAIN_SEEDS = (42, 43, 44)


@dataclass
class Period:
    by_year: list
    n_authors: int
    digest: str


def ir_team(work):
    """Return the unique identified, institution-linked domestic team of an article."""
    rows = work.get("authorships") or []
    if work["is_authors_truncated"] or len(rows) > TEAM_CAP:
        return ()
    team = set()
    for row in rows:
        if not any((inst.get("country_code") or "").upper() == "IR"
                   for inst in row.get("institutions") or []):
            continue
        author = (row.get("author") or {}).get("id") or ""
        matched = AUTHOR_ID.fullmatch(author)
        if matched and matched[1] not in {"A9999999999", "A5317838346"}:
            team.add(matched[1])
    return tuple(sorted(team))


def load_period(directory, first, last):
    all_ids = set()
    work_ids = set()
    yearly = []
    digest = hashlib.sha256()
    for year in range(first, last + 1):
        pages = sorted(directory.glob(f"{year}-*.json.gz"))
        if not pages:
            raise ValueError(f"Missing OpenAlex pages for {year}")
        expected = None
        rows = {}
        for path in pages:
            with gzip.open(path, "rt", encoding="utf8") as f:
                data = json.load(f)
            count = int(data["meta"]["count"])
            if expected is None:
                expected = count
            if expected != count:
                raise ValueError(f"Different counts across pages in {year}")
            for work in data["results"]:
                wid = work["id"]
                field = work["primary_topic"]["field"]["id"].rsplit("/", 1)[-1]
                if work["publication_year"] != year or work["type"] != "article" or field != "31":
                    raise ValueError(f"Work outside declared scope: {wid}")
                if wid in work_ids:
                    raise ValueError(f"Duplicate work ID: {wid}")
                work_ids.add(wid)
                rows[wid] = ir_team(work)
        if len(rows) != expected:
            raise ValueError(f"Incomplete {year} corpus ({len(rows)}/{expected} works)")
        teams = []
        for wid, team in sorted(rows.items()):
            if team:
                teams.append(team)
                all_ids.update(team)
                digest.update(f"{year}|{wid}|{','.join(team)}\n".encode())
        yearly.append(teams)
    index = {aid: i for i, aid in enumerate(sorted(all_ids))}
    return Period([[tuple(index[aid] for aid in team) for team in year] for year in yearly],
                  len(index), digest.hexdigest())


def curveball(years, rng, sweeps):
    """Trade authors across randomly paired papers in the same year.

    Every sweep uses each row once, with a random bye for an odd row count.
    A uniform split of the symmetric difference preserves both margins.
    No-op trades are retained.
    """
    randomized = []
    overlap = assignments = 0
    for original in years:
        rows = [set(team) for team in original]
        ids = list(range(len(rows)))
        for _ in range(sweeps):
            rng.shuffle(ids)
            for i, j in zip(ids[::2], ids[1::2]):
                left, right = rows[i], rows[j]
                common = left & right
                n_left = len(left) - len(common)
                if not n_left or len(right) == len(common):
                    continue
                pool = sorted(left ^ right)
                rng.shuffle(pool)
                rows[i] = common.union(pool[:n_left])
                rows[j] = common.union(pool[n_left:])
        if list(map(len, rows)) != list(map(len, original)):
            raise RuntimeError("Paper team-size margin changed")
        if Counter(a for team in rows for a in team) != Counter(a for team in original for a in team):
            raise RuntimeError("Author annual productivity margin changed")
        overlap += sum(len(team.intersection(original[i])) for i, team in enumerate(rows))
        assignments += sum(map(len, rows))
        randomized.extend(rows)
    return randomized, overlap / assignments


def graph_metrics(teams, n_authors):
    """Project to a simple weighted graph, keep isolates, and optimize Q on its LCC."""
    weights = Counter(pair for team in teams for pair in combinations(sorted(team), 2))
    if not weights:
        raise ValueError("Graph has no edges: LCC modularity is undefined")
    edges = sorted(weights)
    g = ig.Graph(n=n_authors, edges=edges, directed=False)
    g.es["weight"] = [weights[pair] for pair in edges]
    lcc = g.connected_components().giant()
    candidates = []
    for seed in LOUVAIN_SEEDS:
        ig.set_random_number_generator(random.Random(seed))
        parts = lcc.community_multilevel(weights="weight", resolution=1)
        candidates.append((lcc.modularity(parts.membership, weights="weight"), len(parts)))
    q, n_communities = max(candidates, key=lambda item: item[0])
    return {
        "papers": len(teams), "authors": n_authors, "edges": g.ecount(),
        "total_edge_weight": sum(weights.values()), "lcc_nodes": lcc.vcount(),
        "lcc_share": lcc.vcount() / n_authors, "q": q,
        "q_seed_min": min(p[0] for p in candidates), "communities": n_communities
    }


def measure(period, first, kind, rep, sweeps, base_seed):
    if kind == "observed":
        rows = [team for year in period.by_year for team in year]
        overlap = 1.0
        seed = None
    else:
        seed = base_seed + first * 1000000 + rep + (100000 if kind == "double_sweeps" else 0)
        rows, overlap = curveball(period.by_year, random.Random(seed), sweeps)
    return dict(period=f"{first}-{first+4}", type=kind, replicate=rep, trade_seed=seed,
                sweeps=sweeps, original_incidence_retained=overlap,
                **graph_metrics(rows, period.n_authors))


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def calc_summary(statistic, observed, values, alternative):
    mean = statistics.mean(values)
    if alternative == "upper":
        p = (1 + sum(y >= observed for y in values)) / (1 + len(values))
    else:
        # The null contrast can be asymmetric. Use equal tails rather than
        # assuming symmetry about the sample mean of the null differences.
        n_lo = sum(y <= observed for y in values)
        n_hi = sum(y >= observed for y in values)
        p = min(1.0, 2 * (1 + min(n_lo, n_hi)) / (1 + len(values)))
    return dict(statistic=statistic, alternative=alternative, observed=observed,
                n_null=len(values), null_mean=mean, null_sd=statistics.stdev(values),
                null_min=min(values), null_max=max(values), observed_minus_null_mean=observed-mean,
                empirical_p=p)


def run(data_dir, out, reps, sweeps, diagnostics, jobs, seed):
    if reps < 2 or sweeps < 1 or diagnostics < 0 or jobs < 1:
        raise ValueError("Require >=2 randomized pairs, >=1 sweep, >=0 diagnostics, and >=1 worker")
    periods = [(first, load_period(data_dir, first, last)) for first, last in PERIODS]
    rows = []
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        tasks = []
        for first, period in periods:
            tasks.append(pool.submit(measure, period, first, "observed", 0, 0, seed))
            for kind, n, steps in (("null", reps, sweeps), ("double_sweeps", diagnostics, 2*sweeps)):
                for rep in range(1, n + 1):
                    tasks.append(pool.submit(measure, period, first, kind, rep, steps, seed))
        for task in tasks:
            rows.append(task.result())
    obs = [r for r in rows if r["type"] == "observed"]
    nulls = [[r["q"] for r in rows if r["type"] == "null" and r["period"] == o["period"]]
             for o in obs]
    summary = [calc_summary(f"q_{o['period']}", o["q"], values, "upper")
               for o, values in zip(obs, nulls)]
    deltas = [b - a for a, b in zip(*nulls)]
    summary.append(calc_summary("q_late_minus_early", obs[1]["q"] - obs[0]["q"], deltas, "two-sided"))
    meta = {
        "scope": "Iran-linked OpenAlex article; primary field 31; full listed authorships <=50; own IR institution and usable OpenAlex author ID; includes isolates",
        "periods": [p["period"] for p in obs], "projection": "edge weight = number of shared papers",
        "input_sha256_filtered_canonical_incidence_by_period": {str(first): p.digest for first, p in periods},
        "null": "Within publication year, randomly pair papers without replacement each sweep, split their non-shared authors uniformly at random keeping sizes fixed. Each replicate starts from the observed matrix. Both annual author productivity and paper team sizes checked in every replicate.",
        "curveball_reference": "https://doi.org/10.1038/ncomms5114",
        "generated_states": "Finite trades approximate the fixed-margin reference distribution; the double-sweep runs are a mixing sensitivity and are excluded from null p values.",
        "other_constraints": "Institutions, topics within field, collaborators and projected degrees are not held fixed. Every retained paper and domestic authorship count is fixed within year. Each randomized graph uses its own LCC, which may have a different size.",
        "measure": "Weighted undirected modularity Q at resolution 1 on the largest connected component; report the best of three multilevel (Louvain) partitions, both observed and randomized. Community counts refer to the best partition. Heuristic optimization can yield different partitions.",
        "seeds_louvain": LOUVAIN_SEEDS, "seed_trade_base": seed, "null_pairs": reps,
        "sweeps": sweeps, "diagnostic_double_sweep_pairs": diagnostics,
        "inference": "Upper-tail empirical rank for observed Q in each period, and two-sided (twice the smaller +1-corrected tail) for the signed between-period difference against independent matched-index randomized pairs. This conditions on observed yearly author/size margins, not a causal or temporal sampling model.",
        "minimum_one_sided_p": 1/(1+reps), "minimum_two_sided_p": min(1,2/(1+reps)),
        "igraph_version": ig.__version__, "python_version": platform.python_version(),
    }
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "null_replicates.csv", rows)
    write_csv(out / "null_comparison.csv", summary)
    (out / "null_method.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "openalex_physics31_pages")
    parser.add_argument("--output", type=Path, default=ROOT / "null_results")
    parser.add_argument("--replicates", type=int, default=99)
    parser.add_argument("--sweeps", type=int, default=12)
    parser.add_argument("--diagnostics", type=int, default=6)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20261118)
    args = parser.parse_args()
    run(args.input, args.output, args.replicates, args.sweeps, args.diagnostics, args.jobs, args.seed)
