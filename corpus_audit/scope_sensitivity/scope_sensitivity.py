"""Compare coauthorship networks under alternative definitions of physics and affiliation.

The default command recomputes the table using the included compact work records.
Use --refresh PRIMARY_PAGES to rebuild those records from a completed primary-field
download and the OpenAlex supplemental-topic list API. Standard library only.
"""

import argparse
import csv
import gzip
import json
import math
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
YEARS = range(2015, 2025)
CAP = 50
PER_PAGE = 100
INVALID = {"A9999999999", "A5317838346", ""}
API = "https://api.openalex.org/works"
COMPACT = ROOT / "scope_records.jsonl.gz"
SCOPES = ("primary", "any_topic", "primary_no_observed_foreign_institution")
_time_lock = threading.Lock()
_next_allowed = 0.0


def check(condition, message):
    if not condition:
        raise ValueError(message)


def short_id(value):
    return str(value or "").rsplit("/", 1)[-1]


def parameters(year, page):
    return {
        "filter": (f"institutions.country_code:IR,topics.field.id:31,primary_topic.field.id:!31,"
                   f"type:article,publication_year:{year}"),
        "page": page,
        "per_page": PER_PAGE,
        "sort": "publication_date:asc",
        "select": "id,publication_year,type,primary_topic,topics,authorships,is_authors_truncated",
    }


def retrieve(url):
    global _next_allowed
    request = Request(url, headers={"User-Agent": "Iran-physics-scope-sensitivity/1",
                                    "Accept-Encoding": "gzip"})
    for attempt in range(5):
        with _time_lock:
            time.sleep(max(0, _next_allowed - time.monotonic()))
            _next_allowed = time.monotonic() + 0.20
        try:
            with urlopen(request, timeout=90) as response:
                data = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return json.loads(data)
        except HTTPError as exc:
            message = exc.read(512).decode(errors="replace")
            if exc.code not in {429, 500, 502, 503, 504} or "daily_budget" in message or attempt == 4:
                raise RuntimeError(f"OpenAlex returned HTTP {exc.code}: {message}") from exc
            time.sleep(max(float(exc.headers.get("Retry-After") or 0), 2 ** attempt))
        except (TimeoutError, URLError) as exc:
            if attempt == 4:
                raise RuntimeError(f"Could not reach {url}") from exc
            time.sleep(2 ** attempt)


def compact(work, year, primary):
    work_id = short_id(work["id"])
    field = (work["primary_topic"] or {}).get("field") or {}
    main_field = short_id(field.get("id"))
    check(work_id.startswith("W") and work["publication_year"] == year and work["type"] == "article",
          f"Out-of-scope work {work_id}")
    check((main_field == "31") == primary, f"Unexpected primary field in {work_id}")
    if not primary:
        fields = {short_id((t.get("field") or {}).get("id")) for t in work["topics"]}
        check("31" in fields, f"Missing physics topic on {work_id}")
    byline = work["authorships"]
    truncated = work["is_authors_truncated"]
    check(isinstance(byline, list) and isinstance(truncated, bool), f"Incomplete byline on {work_id}")
    foreign = False
    domestic_authors = set()
    for authorship in byline:
        countries = {i.get("country_code") for i in authorship.get("institutions") or []} - {"", None}
        foreign |= bool(countries - {"IR"})
        author_id = short_id((authorship.get("author") or {}).get("id"))
        if "IR" in countries and author_id not in INVALID:
            domestic_authors.add(author_id)
    return {
        "work_id": work_id, "year": year, "primary_field": main_field,
        "authorships_returned": len(byline), "truncated": truncated,
        "non_IR_institution_observed": foreign, "IR_author_ids": sorted(domestic_authors),
    }


def page_at(cache, ypage):
    year, page = ypage
    path = cache / f"{year}-{page:03d}.json.gz"
    url = API + "?" + urlencode(parameters(year, page))
    if not path.exists():
        response = retrieve(url)
        data = {
            "count": response["meta"]["count"],
            "records": [compact(w, year, primary=False) for w in response["results"]],
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "url": url,
        }
        expected = min(PER_PAGE, max(0, data["count"] - PER_PAGE * (page - 1)))
        check(len(data["records"]) == expected, f"Unexpected page length for {year}/{page}")
        temporary = path.with_suffix(".part")
        with gzip.open(temporary, "wt", encoding="utf-8") as fh:
            json.dump(data, fh, separators=(",", ":"))
        temporary.replace(path)
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    check(data["url"] == url, f"Query changed for {path}")
    return year, data["count"]


def annual_expected():
    path = ROOT.parent / "output_stage2" / "population_by_year.csv"
    with path.open(encoding="utf-8-sig") as fh:
        return {int(row["year"]): (int(row["primary_physics"]), int(row["any_physics_topic"]))
                for row in csv.DictReader(fh)}


def refresh(primary_path, cache):
    cache.mkdir(parents=True, exist_ok=True)
    expected = annual_expected()
    with ThreadPoolExecutor(6) as pool:
        counts = dict(pool.map(lambda p: page_at(cache, p), ((y, 1) for y in YEARS)))
        for year, count in counts.items():
            narrow, broad = expected[year]
            check(count == broad - narrow, f"Supplement count disagrees with the audit for {year}: {count}")
        pages = [(y, p) for y in YEARS for p in range(2, math.ceil(counts[y] / PER_PAGE) + 1)]
        for year, count in pool.map(lambda p: page_at(cache, p), pages):
            check(count == counts[year], f"Changing query count for {year}")

    records = []
    seen = set()
    times = []
    for year in YEARS:
        narrow, broad = expected[year]
        start_count = len(seen)
        for page in sorted(primary_path.glob(f"{year}-*.json.gz")):
            with gzip.open(page, "rt", encoding="utf-8") as fh:
                data = json.load(fh)
            check(data["meta"]["count"] == narrow, f"Unexpected primary count for {year}")
            rows = [compact(w, year, primary=True) for w in data["results"]]
            records.extend(rows)
            seen.update(row["work_id"] for row in rows)
        check(len(seen) - start_count == narrow and len(seen) == len(records), f"Primary ID mismatch {year}")
        for number in range(1, math.ceil(counts[year] / PER_PAGE) + 1):
            with gzip.open(cache / f"{year}-{number:03d}.json.gz", "rt", encoding="utf-8") as fh:
                data = json.load(fh)
            times.append(data["retrieved_at_utc"])
            rows = data["records"]
            records.extend(rows)
            seen.update(row["work_id"] for row in rows)
        check(len(seen) - start_count == broad and len(seen) == len(records), f"Broad ID mismatch {year}")

    temporary = COMPACT.with_suffix(".partial")
    with gzip.open(temporary, "wt", encoding="utf-8") as fh:
        for row in records:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")
    temporary.replace(COMPACT)
    with (ROOT / "scope_manifest.json").open("w", encoding="utf-8") as fh:
        json.dump({
            "source": API, "supplement_first_utc": min(times), "supplement_last_utc": max(times),
            "supplement_queries": [parameters(year, 1)["filter"] for year in YEARS],
            "retrieval": "100 works/page, sorted by publication date; count and uniqueness checked by year.",
            "unique_records": len(seen), "supplement_counts_by_year": counts,
            "paper_eligibility": "Untruncated byline with at most 50 total returned authorships and >=1 usable IR author ID.",
            "affiliation": "An author has IR on at least one of their institutions on the work.",
            "foreign_country_rule": "Exclude a work if any identified institution of any author has a non-IR country. Unidentified countries are retained.",
            "unresolved_author_ids": ["missing", "A9999999999", "A5317838346"],
        }, fh, indent=2)


def largest_component(graph):
    remaining = set(graph)
    largest = 0
    while remaining:
        queue = [remaining.pop()]
        size = 0
        while queue:
            node = queue.pop()
            size += 1
            fresh = graph[node] & remaining
            remaining -= fresh
            queue.extend(fresh)
        largest = max(largest, size)
    return largest


def compute(records, scope, start, end):
    graph = {}
    papers = Counter()
    for work in records:
        if not start <= work["year"] <= end:
            continue
        if scope != "any_topic" and work["primary_field"] != "31":
            continue
        if scope == "primary_no_observed_foreign_institution" and work["non_IR_institution_observed"]:
            continue
        papers["in_scope"] += 1
        authors = work["IR_author_ids"]
        if not authors or work["truncated"] or work["authorships_returned"] > CAP:
            continue
        papers["in_graph"] += 1
        for author in authors:
            graph.setdefault(author, set())
        for left, right in combinations(authors, 2):
            graph[left].add(right)
            graph[right].add(left)
    n = len(graph)
    edges = sum(map(len, graph.values())) // 2
    lcc = largest_component(graph)
    return {
        "scope": scope, "period": f"{start}-{end}", "papers_scope_before_cap": papers["in_scope"],
        "papers_in_network": papers["in_graph"], "nodes": n, "edges": edges,
        "mean_degree": 2 * edges / n if n else None, "lcc_nodes": lcc,
        "lcc_share": lcc / n if n else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", type=Path, metavar="PRIMARY_PAGES")
    parser.add_argument("--cache", type=Path, default=ROOT / "supplement_pages")
    args = parser.parse_args()
    if args.refresh:
        refresh(args.refresh, args.cache)
    with gzip.open(COMPACT, "rt", encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh]
    check(len({row["work_id"] for row in records}) == len(records), "Duplicate work IDs in compact records")
    rows = [compute(records, scope, start, end)
            for scope in SCOPES for start, end in ((2015, 2019), (2020, 2024))]
    with (ROOT / "scope_comparison.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
