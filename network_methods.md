# Coauthorship among Iran-affiliated authors in physics and astronomy

This project compares two five-year OpenAlex coauthorship networks, 2015–2019 and 2020–2024. An author enters a period's graph when their own authorship lists an institution in Iran on an eligible article. Each undirected edge connects two such authors. Its integer weight is the number of distinct eligible articles the authors wrote together.

## Reproduce the analysis

Use Python 3.10 or newer and install the dependencies in `requirements.txt`. The default entry point is `stage3_full_network.py`.

```sh
python -m pip install -r requirements.txt
python stage3_full_network.py
```

The default run retrieves OpenAlex list pages into `openalex_physics31_pages/` and writes the two networks and their comparison to `output_physics31/`. Annual queries use basic pagination, up to 100 works per page. The year with the most works in the archived collection fits within the 10,000-result limit. A free API key can be supplied through the optional `OPENALEX_API_KEY` environment variable. Saved pages are reusable across runs.

To reproduce the analysis from a complete saved page collection, run:

```sh
python stage3_full_network.py --cache openalex_physics31_pages --offline --output output_physics31
```

Each page stores its query URL, retrieval time, API metadata and results. The analysis checks the query parameters, page size and position, unique work IDs, reported year totals, article type and the primary field ID and name on every article. The fields endpoint supplies the field metadata for a new online collection. Subsequent runs check the saved field record and can reuse a complete page collection without a network connection. Refreshing the corpus in a separate cache gives a new snapshot. OpenAlex periodically revises past records.

## Corpus and graph

A work must have type `article`, primary field [Physics and Astronomy (31)](https://api.openalex.org/fields/31), and at least one Iranian institution according to the work-level filter. Publication year places the work in a period. Each graph uses the Iranian institution on the author’s record for the article. Authors with dual affiliations can qualify. Authorships with missing or unresolved IDs, including OpenAlex's null and deleted-author placeholders, cannot form nodes. The article is eligible if at least one identified author qualifies. A qualifying author without a qualifying collaborator remains an isolate unless another article connects them.

The primary analysis accepts papers with up to **50 total listed authorships** before filtering their affiliations. Sensitivity runs use cutoffs of 20 and 100. Team size counts authorship positions on the complete OpenAlex record, including those with unresolved author IDs. OpenAlex caps list responses at 100 authorships. Papers flagged as truncated are excluded for all three cutoffs. A complete 100-author paper is eligible at the 100 cutoff. Counts of exclusions are reported separately. The coauthor graph includes a single node per distinct eligible author ID on each article.

## Measurements and files

- `comparison.csv` contains the primary networks. `team_size_sensitivity.csv` contains all six period–threshold combinations. Blank metric values indicate an undefined denominator.
- `nodes_*.csv` and `edges_*.csv` describe the primary graphs. Node degree counts distinct domestic-affiliated collaborators. Weighted degree sums edge weights. The fraction of repeated edges counts pairs with two or more shared eligible articles in that period, divided by all connected pairs.
- The largest connected component (LCC) share uses all graph nodes as its denominator. Mean local clustering uses unweighted links and averages over all vertices, with zeros for degree zero or one. Transitivity is three times the number of triangles divided by the number of connected triples.
- Weighted Louvain community detection runs on the LCC at resolution 1 using seeds 42, 43 and 44. The reported partition has the highest modularity of the three runs. Community IDs are specific to the period and partition. Connected components and communities answer different questions.
- `degree_distribution_*.csv` gives counts including isolates. `degree_distribution.png` shows the complementary cumulative distribution for positive degrees; the denominator includes all authors. `component_sizes_*.csv` gives component size frequencies.
- `method_manifest.json` records filters, yearly counts and paging times, selection rules and package versions. `RESULTS.md` summarizes the primary comparison.

Field classification applies to the article. Within-field classification, historical coverage, institutional matching and author disambiguation can affect the measured change. The graph describes coauthorship reported through domestic affiliations. Distinct people can be merged into one author ID or split across several. The two five-year windows also differ in the researchers and articles they cover. A change in modularity alone does not establish statistical significance or explain its cause.

## References

Roohi, A. A., Shirazi, A. H., Kargaran, A., and Jafari, G. R. (2010). Local model of a scientific collaboration in physics network compared with the global model. *Physica A*, 389, 5530–5537. [DOI](https://doi.org/10.1016/j.physa.2010.08.007).

[OpenAlex work attributes](https://help.openalex.org/data/works/attributes/) · [OpenAlex author disambiguation](https://help.openalex.org/data/authors/disambiguation/) · [OpenAlex API](https://help.openalex.org/api/).
