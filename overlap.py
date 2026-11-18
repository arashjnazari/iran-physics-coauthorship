"""Describe persistence of recorded coauthor links among authors active in both windows."""
import argparse
import csv
from pathlib import Path

def read_nodes(path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        return {r['author_id'] for r in csv.DictReader(f)}

def read_edges(path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        return {tuple(sorted((r['source'],r['target']))): int(r['weight']) for r in csv.DictReader(f)}

def overlap(source):
    periods=('2015-2019','2020-2024')
    nodes = [read_nodes(source / f'nodes_{p}.csv') for p in periods]
    edges = [read_edges(source / f'edges_{p}.csv') for p in periods]
    common = nodes[0] & nodes[1]
    shared = edges[0].keys() & edges[1].keys()
    restricted=[{uv for uv in e if uv[0] in common and uv[1] in common} for e in edges]
    assert restricted[0] & restricted[1] == shared
    return {'common_authors':len(common),'authors_first_only':len(nodes[0]-nodes[1]),'authors_second_only':len(nodes[1]-nodes[0]),'first_edges_between_common_authors':len(restricted[0]),'second_edges_between_common_authors':len(restricted[1]),'edges_in_both':len(shared),'fraction_first_edges_observed_again_between_common_authors':len(shared)/len(restricted[0]) if restricted[0] else None}

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--results',required=True,type=Path)
    args=ap.parse_args();r=overlap(args.results)
    with (args.results/'cross_period_overlap.csv').open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=r);writer.writeheader();writer.writerow(r)
    print(r)
