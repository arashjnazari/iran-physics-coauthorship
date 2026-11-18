# Metadata and field coverage in a sample of 30 works

We sampled 15 works uniformly within each five-year period from the full retrieved corpus, using seed 418. All 26 DOI records retrieved from Crossref had an exact normalized title match. Two DOI queries returned HTTP 404 and two OpenAlex records had no DOI. These four works remained unverified by the Crossref title check. Six of the 26 Crossref deposits contained affiliation text. All six named Iran. Ten of the 26 had at least one ORCID in common with the OpenAlex authorships. These checks cover the identity of individual works and selected authorships. They give no estimate of author-ID splits or merges across papers.

## What the field covers

The sample includes black-hole thermodynamics, spin networks and quantum transport. OpenAlex also assigns field 31 to occupational noise on an oil rig (W2298833263), sonochemical nanoparticle synthesis (W2593724625), and a molecular-structure study using density-functional theory (W4313367618). The sample therefore illustrates the difference between a paper's indexed field and its authors' academic disciplines.

OpenAlex raw affiliation text explicitly named Iran on at least one institution-resolved authorship in 28 of 30 records. A paper on radiation in Hamadan schools illustrates incomplete institutional matching. All five authors had raw affiliations naming Iran. OpenAlex resolved the university affiliations of three authors. It returned no institution for the high school and education office listed by the other two authors. The projected graph includes three of the five authors on this work. [OpenAlex record W3136797378](https://openalex.org/W3136797378)

## Title-based sensitivity

One sampled record from 2015 is a removal notice for a paper on plasma-assisted polymer treatment. Both databases give the same title, and the OpenAlex article-type filter admits the three-author record. [Crossref record for the removal notice](https://api.crossref.org/works/10.1016/j.ecss.2015.11.021)

Across the 25,590 records, an English title-prefix screen identified 40 explicitly marked retracted articles, six withdrawn articles and one removal notice. It also screened for retraction notices, errata, corrigenda, corrections and expressions of concern. All 47 records qualified for the principal graph. Dropping them removed 36 works from the earlier network and 11 from the later one.

| Measure after excluding the flagged records | 2015–2019 | 2020–2024 |
|---|---:|---:|
| Authors | 11,756 | 10,831 |
| Distinct coauthor pairs | 21,740 | 19,998 |
| Authors in the largest component | 6,666 | 5,726 |
| Largest component share | 56.70% | 52.87% |
| Weighted modularity on the largest component | 0.9172 | 0.9291 |

The decline in connected share and the rise in observed modularity persist. The screen detects status markers at the start of the title. Unlabelled retractions, later notices and non-English markers can escape it. The main analysis uses the original eligibility criteria. Each screened record and both graph reconstructions are listed in `title_notice_flags.csv` and `title_notice_sensitivity.csv`.
