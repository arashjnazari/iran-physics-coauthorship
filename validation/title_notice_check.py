"""Rebuild the weighted coauthor networks after excluding records with status-marked titles."""
import argparse
import csv
import gzip
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "null_analysis.py").is_file() else HERE.parent
sys.path.insert(0, str(ROOT))
from null_analysis import PERIODS, graph_metrics, ir_team


TITLE_PREFIX = re.compile(
    r"^\s*(?:removal notice\b|retraction\s+(?:notice|note)\b|retraction\s*[:-]|"
    r"retracted\s*(?:article)?\s*[:-]|withdrawal\s+notice\b|withdrawn\s*[:-]|"
    r"errat(?:a|um)\b|corrigenda?\b|corrigendum\b|(?:publisher|author)(?:[’']s)?\s+correction\b|"
    r"correction\s*(?:to\b|[:-])|(?:editorial\s+)?expression of concern\b)", re.IGNORECASE
)
FLAG_FIELDS = ("year", "openalex_id", "doi", "flagged_prefix", "title", "eligible_domestic_authors")


def year_records(directory, year):
    """Require distinct records and reconcile the annual count before using the pages."""
    seen = set()
    expected = None
    for path in sorted(directory.glob(f"{year}-*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            page = json.load(f)
        n = int(page["meta"]["count"])
        if expected is not None and n != expected:
            raise ValueError(f"Inconsistent counts across pages for {year}")
        expected = n
        for work in page["results"]:
            field = work["primary_topic"]["field"]["id"].rsplit("/", 1)[-1]
            if work["id"] in seen or work["publication_year"] != year or field != "31" or work["type"] != "article":
                raise ValueError(f"Duplicate or out-of-scope work {work['id']}")
            seen.add(work["id"])
            yield work
    if expected is None or len(seen) != expected:
        raise ValueError(f"Incomplete collection for {year}: {len(seen)} of {expected}")


def write_table(path, fieldnames, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run(directory, output):
    flagged = []
    comparison = []
    for first, last in PERIODS:
        teams_with_status = []
        for year in range(first, last + 1):
            for work in year_records(directory, year):
                prefix = TITLE_PREFIX.match(work.get("title") or "")
                team = ir_team(work)
                if prefix:
                    flagged.append(dict(year=year, openalex_id=work["id"], doi=work.get("doi"),
                                        flagged_prefix=prefix.group().strip(), title=work["title"],
                                        eligible_domestic_authors=len(team)))
                if team:
                    teams_with_status.append((team, bool(prefix)))
        for drop in (False, True):
            teams = [team for team, flagged_title in teams_with_status if not (drop and flagged_title)]
            authors = sorted({a for team in teams for a in team})
            index = {aid: i for i, aid in enumerate(authors)}
            integer_teams = [[index[aid] for aid in team] for team in teams]
            metrics = graph_metrics(integer_teams, len(authors))
            comparison.append(dict(period=f"{first}-{last}",
                                   scope="exclude_flagged_titles" if drop else "all_eligible", **metrics))
    output.mkdir(parents=True, exist_ok=True)
    write_table(output / "title_notice_flags.csv", FLAG_FIELDS, flagged)
    write_table(output / "title_notice_sensitivity.csv", list(comparison[0]), comparison)
    print(f"Flagged {len(flagged)} records; wrote four graph summaries to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "openalex_physics31_pages", help="directory of annual OpenAlex pages")
    parser.add_argument("--output", type=Path, default=HERE, help="directory for the two sensitivity tables")
    args = parser.parse_args()
    run(args.input, args.output)
