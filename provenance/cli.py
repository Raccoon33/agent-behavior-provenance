"""Offline trajectory analysis; never substitutes fixture data for missing logs."""
import argparse
import json
from pathlib import Path
from .report import analyze,compare
from .responses import analyze_responses
from .slice import backward_slice
import networkx as nx


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('analyze'); a.add_argument('--run',type=Path,required=True); a.add_argument('--output',type=Path,required=True)
    a.add_argument('--snapshot-only',action='store_true',help='Explicitly allow no trajectory; report only final integrity, never agent outcomes')
    r = sub.add_parser('analyze-responses', help='Analyze a completed CSV experiment harness run')
    r.add_argument('--run', type=Path, required=True)
    r.add_argument('--output', type=Path, required=True)
    c=sub.add_parser('compare'); c.add_argument('--baseline',required=True); c.add_argument('--injected',required=True); c.add_argument('--output',required=True)
    s=sub.add_parser('slice'); s.add_argument('--graph',required=True); s.add_argument('--target',required=True)
    args=p.parse_args()
    try:
        if args.command=='analyze': analyze(args.run,args.output,args.snapshot_only)
        elif args.command=='analyze-responses': analyze_responses(args.run, args.output)
        elif args.command=='compare': compare(args.baseline,args.injected,args.output)
        else: print(json.dumps(backward_slice(nx.read_graphml(args.graph),args.target),indent=2))
    except (OSError,ValueError,TypeError,KeyError) as err:
        p.exit(2,f'Error: {err}\n')

if __name__=='__main__': main()
