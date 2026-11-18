"""Audit the paper population and author metadata for an Iranian physics coauthorship study."""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

FIELD = 31
FIELD_NAME = "Physics and Astronomy"
API = "https://api.openalex.org"
PERIODS = [(2015, 2019), (2020, 2024)]
SAMPLE_SIZE = 100
SEED = 42
OUT = Path(__file__).resolve().parent / "output_stage2"

# The NULL author and the deleted-author marker do not identify researchers.
UNRESOLVED = {
    None,
    "",
    "https://openalex.org/A9999999999",
    "https://openalex.org/A5317838346",
}


def query(path, params):
    url = f"{API}/{path}?" + urlencode(params)
    request = Request(url, headers={"User-Agent": "Iran-physics-network-corpus-audit/2"})
    for attempt in range(4):
        try:
            with urlopen(request, timeout=55) as response:
                return json.load(response), url
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 3:
                raise RuntimeError(f"OpenAlex returned HTTP {exc.code} for {url}") from exc
        except (TimeoutError, URLError) as exc:
            if attempt == 3:
                raise RuntimeError(f"Cannot reach {url}") from exc
        sleep(2 ** attempt)


def work_filter(start, end, field_key):
    return (
        f"institutions.country_code:IR,{field_key}:{FIELD},type:article,"
        f"from_publication_date:{start}-01-01,to_publication_date:{end}-12-31"
    )


def save_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def verify_field(field):
    field_id = str(field.get("id", "")).rsplit("/", 1)[-1]
    if field_id != str(FIELD) or field.get("display_name") != FIELD_NAME:
        raise ValueError(f"Unexpected OpenAlex field identity: {field}")


def author_ids(authorships):
    return {(a.get("author") or {}).get("id") for a in authorships} - UNRESOLVED


def audit_work(work, period):
    field = (work.get("primary_topic") or {}).get("field") or {}
    verify_field(field)
    authorships = work["authorships"] or []
    domestic = [
        author for author in authorships
        if any(inst.get("country_code") == "IR" for inst in author.get("institutions") or [])
    ]
    # With a truncated byline the number returned is only a lower bound on the full team.
    return {
        "period": period,
        "work_id": work["id"],
        "year": work["publication_year"],
        "title": work["title"],
        "primary_field_id": FIELD,
        "primary_field_name": field["display_name"],
        "authorships_returned": len(authorships),
        "distinct_all_author_ids_returned": len(author_ids(authorships)),
        "ir_affiliated_authorships_returned": len(domestic),
        "distinct_ir_author_ids_returned": len(author_ids(domestic)),
        "is_authors_truncated": bool(work.get("is_authors_truncated")),
        "over_50_authors_returned": len(authorships) > 50,
    }


def count_populations(queries):
    first, last = PERIODS[0][0], PERIODS[-1][1]
    annual = {year: {"year": year} for year in range(first, last + 1)}
    for name, field_key in (
        ("primary_physics", "primary_topic.field.id"),
        ("any_physics_topic", "topics.field.id"),
    ):
        params = {"filter": work_filter(first, last, field_key), "group_by": "publication_year"}
        response, url = query("works", params)
        queries.append(url)
        counts = {int(row["key"]): int(row["count"]) for row in response["group_by"]}
        total = int(response["meta"]["count"])
        if set(annual) != set(counts) or sum(counts.values()) != total:
            raise ValueError(f"Inconsistent annual counts: {name}")
        for year, count in counts.items():
            annual[year][name] = count
        save_json(OUT / f"annual_{name}_response.json", {
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "query": url,
            "count": total,
            "group_by": response["group_by"],
        })
    return annual


def audit_period(start, end, annual, queries):
    period = f"{start}-{end}"
    params = {
        "filter": work_filter(start, end, "primary_topic.field.id"),
        "sample": SAMPLE_SIZE,
        "seed": SEED,
        "per_page": SAMPLE_SIZE,
        "select": "id,title,publication_year,primary_topic,authorships,is_authors_truncated",
    }
    response, url = query("works", params)
    queries.append(url)
    rows = [audit_work(work, period) for work in response["results"]]
    if len(rows) != SAMPLE_SIZE or len({row["work_id"] for row in rows}) != SAMPLE_SIZE:
        raise ValueError(f"Unexpected sample size in {period}")
    retained = [
        row for row in rows if not row["is_authors_truncated"] and not row["over_50_authors_returned"]
    ]
    years = range(start, end + 1)
    summary = {
        "period": period,
        "primary_physics_population": sum(annual[y]["primary_physics"] for y in years),
        "any_physics_population": sum(annual[y]["any_physics_topic"] for y in years),
        "sampled_papers": len(rows),
        "sample_papers_over_50_returned": sum(r["over_50_authors_returned"] for r in rows),
        "sample_papers_truncated": sum(r["is_authors_truncated"] for r in rows),
        "sample_papers_included_at_cap_50": len(retained),
        "mean_distinct_ir_authors_included": round(mean(r["distinct_ir_author_ids_returned"] for r in retained), 3) if retained else None,
        "mean_distinct_all_authors_included": round(mean(r["distinct_all_author_ids_returned"] for r in retained), 3) if retained else None,
        "included_papers_no_identified_ir_author": sum(r["distinct_ir_author_ids_returned"] == 0 for r in retained),
    }
    return rows, summary


def main():
    field, url = query(f"fields/{FIELD}", {"select": "id,display_name"})
    verify_field(field)
    OUT.mkdir(parents=True, exist_ok=True)
    queries = [url]
    annual = count_populations(queries)
    save_csv(OUT / "population_by_year.csv", list(annual.values()))
    audit, summaries = [], []
    for start, end in PERIODS:
        rows, summary = audit_period(start, end, annual, queries)
        audit.extend(rows)
        summaries.append(summary)

    save_csv(OUT / "paper_metadata_audit.csv", audit)
    save_csv(OUT / "period_summary.csv", summaries)
    save_json(OUT / "method_manifest.json", {
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "field_identity": field,
        "source": API,
        "country": "IR",
        "type": "article",
        "seed": SEED,
        "sample_size_per_period": SAMPLE_SIZE,
        "queries": queries,
        "population_unit": "OpenAlex works, before team-size and author-ID exclusions.",
        "sample_author_summary": (
            "Means use only untruncated works with at most 50 returned authorships. "
            "Iran affiliation is determined on each authorship's institutions on that work."
        ),
    })
    print(*summaries, sep="\n")


if __name__ == "__main__":
    main()
