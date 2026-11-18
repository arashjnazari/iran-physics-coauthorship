"""Regression tests for the corpus and graph definitions."""
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

import stage3_full_network as s


def authorship(n, country="IR"):
    aid = f"https://openalex.org/A{n}" if n is not None else None
    return {"author": {"id": aid, "display_name": str(n)}, "institutions": [{"country_code": country}]}


def work(year, number, members):
    return {"id": f"https://openalex.org/W{year}{number}", "publication_year": year, "type": "article",
            "primary_topic": {"field": {"id": s.FIELD_URL, "display_name": s.FIELD_NAME}},
            "authorships": members, "is_authors_truncated": False}


def page(year, rows):
    return {"query_url": s.API + "?" + urlencode(s.params_for(year, 1)), "retrieved_at_utc": "2026-11-18T00:00:00Z",
            "meta": {"page": 1, "per_page": 100, "count": len(rows)}, "results": rows}


class CorpusTest(unittest.TestCase):
    def test_field_and_completeness(self):
        y = 2015
        p = page(y, [work(y, 1, [])])
        s.verify_page(p, y, 1)
        p["results"][0]["primary_topic"]["field"]["id"] = "https://openalex.org/fields/27"
        with self.assertRaises(ValueError):
            s.verify_page(p, y, 1)
        p = page(y, [])
        p["meta"]["count"] = 1
        with self.assertRaises(ValueError):
            s.verify_page(p, y, 1)

    def test_placeholder_cutoffs_and_metrics(self):
        a = authorship
        source = [work(2015, i, group) for i, group in enumerate([
            [a(1), a(2), a(3), a(1), a(4, "GB")],
            [a(1), a(2)], [a(3), a(4)], [a(5), a(9999999999), a(5317838346)],
            [a(None)], [a(6, "GB")], [a(1), a(80)] + [a(n, "GB") for n in range(100, 149)],
            [a(6)] + [a(n, "GB") for n in range(100, 199)],
            [a(6)] + [a(n, "GB") for n in range(100, 199)]])]
        source[-1]["is_authors_truncated"] = True
        compact = list(map(s.compact_work, source))
        graph, counts = s.build_graph(compact, 50)
        row, _, partition = s.measure(graph, "toy", 50, counts)
        self.assertEqual((row["nodes"], row["edges"], row["edge_weight_sum"]), (5, 4, 5))
        self.assertEqual((row["isolates"], row["repeated_edges"], row["papers_in_network"]), (1, 1, 4))
        self.assertEqual(row["excluded_large_complete_team"], 2)
        self.assertEqual(row["excluded_truncated"], 1)
        self.assertEqual(row["unresolved_ir_authorships_after_team_filter"], 3)
        self.assertAlmostEqual(row["mean_local_clustering"], 7/15)
        self.assertAlmostEqual(row["transitivity"], 3/5)
        self.assertAlmostEqual(row["mean_degree"], 8/5)
        self.assertAlmostEqual(row["lcc_share"], 4/5)
        self.assertEqual(sum(map(len, partition)), 4)
        graph100, counts100 = s.build_graph(compact, 100)
        self.assertEqual(graph100.number_of_nodes(), 7)
        self.assertEqual(counts100["papers_in_network"], 6)

    def test_end_to_end_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache, out = Path(tmp) / "cache", Path(tmp) / "results"
            cache.mkdir()
            for y in s.YEARS:
                rows = [work(y, 1, [authorship(y), authorship(y + 1)])]
                with gzip.open(cache / f"{y}-001.json.gz", "wt") as f:
                    json.dump(page(y, rows), f)
            with patch.object(s, "request_json", side_effect=AssertionError("offline run attempted a download")):
                s.run(cache, out, offline=True)
            self.assertTrue((out / "edges_2020-2024.csv").is_file())
            with (out / "comparison.csv").open() as f:
                rows = list(s.csv.DictReader(f))
            self.assertEqual(len(rows), 2)
            self.assertEqual([r["nodes"] for r in rows], ["6", "6"])
            self.assertEqual([r["edges"] for r in rows], ["5", "5"])
            self.assertEqual([r["mean_local_clustering"] for r in rows], ["0.0", "0.0"])


if __name__ == "__main__":
    unittest.main()
