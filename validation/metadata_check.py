"""Check a stratified sample of the retrieved works against Crossref deposits.

Run from the package root with --pages pointing to the cached OpenAlex pages.
Publisher-assigned DOI and title matches check work identity. They do not
establish whether two records belonging to one person were merged correctly.
"""
import argparse
import csv
from datetime import datetime, timezone
from difflib import SequenceMatcher
import gzip
from html import unescape
import json
from pathlib import Path
import random
import re
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

def normalized(s):
    s = re.sub(r'<[^>]+>', '', unescape(s))
    return ''.join(c for c in unicodedata.normalize('NFKD', s.casefold()) if c.isalnum())

def crossref(doi):
    if not doi:
        return {}, "missing DOI"
    url = 'https://api.crossref.org/works/' + quote(doi.removeprefix('https://doi.org/'), safe='/')
    for attempt in range(3):
        try:
            req = Request(url, headers={"User-Agent": "IranPhysicsMetadataCheck/1.0", "Accept": "application/json"})
            with urlopen(req, timeout=12) as response:
                return json.load(response)['message'], "retrieved"
        except HTTPError as e:
            if e.code < 500 and e.code != 429:
                return {}, f"HTTP {e.code}"
            error = f"HTTP {e.code}"
        except (TimeoutError, URLError, ValueError) as e:
            error = str(e)
        time.sleep(1.5 * (attempt+1))
    return {}, error

def audit(w):
    doi = w.get('doi') or ''
    other, status = crossref(doi)
    t = w['title'] or ''
    t2 = (other.get('title') or [''])[0]
    affs = [a for a in w['authorships'] if any(i.get('country_code')=='IR' for i in a.get('institutions') or [])]
    irtext = [s for a in affs for s in a.get('raw_affiliation_strings') or [] if re.search(r'\biran\b',s,re.I)]
    caff = [s['name'] for a in other.get('author') or [] for s in a.get('affiliation') or [] if s.get('name')]
    o_orcids = {a.get('author',{}).get('orcid','') for a in w['authorships']} - {None,''}
    c_orcids = {a.get('ORCID','') for a in other.get('author') or []} - {None,''}
    return {'period':'2015-2019' if w['publication_year']<2020 else '2020-2024','year':w['publication_year'],'openalex_work':w['id'],'doi':doi,'openalex_title':t,'crossref_status':status,'crossref_title':t2,'normalized_title_similarity':round(SequenceMatcher(None,normalized(t),normalized(t2)).ratio(),3) if t2 else '',
     'openalex_primary_subfield':w['primary_topic']['subfield']['display_name'],'listed_authorships':len(w['authorships']),
     'author_list_truncated':w['is_authors_truncated'],'listed_ir_affiliated_authorships':len(affs),'example_raw_ir_affiliation':irtext[0] if irtext else '',
     'crossref_provides_affiliations':bool(caff) if other else '', 'iran_named_in_crossref_affiliations':any(re.search(r'\biran\b',s,re.I) for s in caff) if caff else '',
     'matched_author_orcids':len(o_orcids & c_orcids) if other else '', 'checked_at_utc':datetime.now(timezone.utc).isoformat()}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--pages',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    records=[{},{}]
    for path in sorted(args.pages.glob('????-???.json.gz')):
        with gzip.open(path,'rt') as f: d=json.load(f)
        for w in d['results']:records[int(w['publication_year']>=2020)][w['id']]=w
    if not all(records):raise ValueError('Both period caches are required.')
    rng=random.Random(418)
    picked=[bucket[k] for bucket in records for k in rng.sample(sorted(bucket),15)]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(3) as pool:
        rows=list(pool.map(audit,picked))
    args.output.parent.mkdir(exist_ok=True,parents=True)
    with args.output.open('w',encoding='utf-8-sig',newline='') as fp:
        writer=csv.DictWriter(fp,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
    for row in rows:
        print(row['year'],row['normalized_title_similarity'],row['crossref_status'],row['openalex_title'])
if __name__=='__main__':main()
