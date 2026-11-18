# Coauthorship among Iran-affiliated researchers in physics and astronomy

How did the structure of coauthorship change between 2015–2019 and 2020–2024? The study starts from OpenAlex articles and identifies each author's institutional affiliations on the article. It compares the full eligible graphs for two five-year periods. The data snapshot was collected on 18 November 2026.

The [two-page Persian research brief](iran-physics-research-brief-fa.pdf) summarizes the findings and the 2010 paper that motivated the study. The [methods](network_methods.md) explain the corpus, the graph construction and each network measure.

## Findings

| Measure | 2015–2019 | 2020–2024 |
|---|---:|---:|
| Articles in the primary-field corpus | 13,583 | 12,007 |
| Articles contributing at least one identified author | 12,754 | 11,321 |
| Distinct author IDs | 11,777 | 10,838 |
| Distinct coauthor pairs | 21,805 | 20,004 |
| Mean number of distinct collaborators | 3.703 | 3.691 |
| Authors in the largest connected component | 6,685 (56.76%) | 5,727 (52.84%) |
| Transitivity | 0.326 | 0.391 |
| Weighted modularity of the largest component | 0.9180 | 0.9292 |

The connected share fell by 3.92 percentage points. The sign of the change persisted at paper-size limits of 20 and 100 authors. With a broader field definition (any assigned topic in physics and astronomy), the connected share fell from 60.28% to 57.49%, while mean degree rose from 3.879 to 4.019. Thus the change in mean degree depends on the definition of physics. See the [team-size results](output_physics31/team_size_sensitivity.csv) and the [field and affiliation comparisons](corpus_audit/scope_sensitivity/scope_comparison.csv).

Among the 3,887 author IDs appearing in both periods, there were 6,090 distinct pairs with a joint article in the first period. Of these pairs, 2,878 (47.26%) also had a joint article in the second period. This comparison is restricted to pairs whose two authors were observed in both windows. The calculation uses [cross-period overlap](output_physics31/cross_period_overlap.csv).

### Community structure under random reassignment

Each year was randomized separately, preserving the number of papers contributed by every eligible author and the eligible team size of each article. The real and randomized graphs use the same weighted projection and Louvain settings on their respective largest connected components. In both periods the observed modularity exceeded all 99 reference values. The difference between the periods was +0.0112 in the data and +0.0318 on average across 99 independent pairs of randomizations. Excess modularity above each period's reference mean decreased from 0.3415 to 0.3209. This comparison is conditional on the specified random-assignment model. Institutional and subfield composition can also shape the partitions. See the [null-model results](null_results/null_comparison.csv) and [protocol](null_results/null_method.json).

## Data and coverage

The principal corpus contains 25,590 unique OpenAlex works with type `article`, primary field 31 (Physics and Astronomy), and at least one institution in Iran. The program verifies the field ID and name against each retrieved record, checks every page, and reconciles annual totals with unique work IDs. The broader topical sensitivity includes 42,345 unique works, including the primary corpus. Results in this package supersede an earlier population audit that used field 27 (Medicine).

An author's own authorship must list a resolved Iranian institution and a usable author ID. Each undirected edge counts joint articles. A sole eligible author contributes a node and can have degree zero. The principal graph includes complete bylines with at most 50 total authors. In the first period 540 bylines were truncated, 16 complete bylines exceeded the cap, and 273 otherwise eligible papers had no usable domestic author ID. In the second period the corresponding counts were 401, 27 and 258. The primary corpus includes records marked as retracted or withdrawn. Removing 47 records with status-marked titles left the direction of the change in connected share intact. See the [30-record audit and case details](validation/sample_review.md).

The counts refer to recognized affiliations in a bibliographic index and to physics as classified at the work level. Researchers' nationalities and motivations are outside the data. The periods are repeated cross-sections of work-based networks. Author-ID errors, changes in coverage, shifts in subfields and the byline cap affect interpretation. The protocol and checks were assembled during exploratory analysis.

## Reproduction

The package includes all pages and the computed results. Python 3.10 or newer and the packages in `requirements.txt` are needed to rerun the principal network calculations. With the included cache the following commands work offline.

```sh
python -m pip install -r requirements.txt
python stage3_full_network.py --offline
python -m unittest test_stage3
python null_analysis.py --jobs 2
python overlap.py --results output_physics31
python corpus_audit/scope_sensitivity/scope_sensitivity.py
python validation/title_notice_check.py --input openalex_physics31_pages --output validation
```

Installing missing software requires network access. The default entry point `stage3_full_network.py` also works without command-line arguments with the packaged cache. Its output includes node and weighted edge tables for both periods. The [corpus audit](corpus_audit/output_stage2/period_summary.csv) includes population counts and a separate sample of 100 papers per period. Running `corpus_audit/stage2_corpus_audit.py` re-queries OpenAlex. The bibliographic sample can be refreshed using `python validation/metadata_check.py --pages openalex_physics31_pages --output validation/metadata_sample.csv`, which contacts Crossref.

## Earlier study

Roohi, A. A., Shirazi, A. H., Kargaran, A., and Jafari, G. R. (2010). Local model of a scientific collaboration in physics network compared with the global model. *Physica A*, 389, 5530–5537. The authors selected 300 physicists working in Iran and used 3,968 ISI Web of Knowledge papers. Their comparison with Newman's Los Alamos network provides historical context. Sample construction and observation windows differ from the present study. [Original article](https://doi.org/10.1016/j.physa.2010.08.007).
