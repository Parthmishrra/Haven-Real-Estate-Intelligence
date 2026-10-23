"""Small, transparent retrieval regression set; no paid judge or hallucination score."""
import argparse
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.store import Store, Retriever
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--semantic',action='store_true',help='Loads the actual MiniLM/FAISS stack; may download models.')
args=parser.parse_args()
cases=[
 ('canopy','Are pets allowed?','canopy-hoa','two domestic pets'),
 ('canopy','How much is the security deposit?','canopy-lease','1,50,000'),
 ('canopy','What is the notice period?','canopy-lease','60 days'),
 ('cedar','What is the rent?','cedar-lease','32,000'),
 ('parkside','How many parking bays?','parkside-lease','Two covered parking'),
]
with tempfile.TemporaryDirectory() as temp:
    store=Store(temp);store.seed(json.loads((ROOT/'dist/assets/sample-data.json').read_text()))
    retriever=Retriever(store,'semantic' if args.semantic else 'lexical')
    hits=0
    for prop,q,doc,expected in cases:
        sources,mode=retriever.search(q,prop)
        passed=any(s['doc_id']==doc and expected.lower() in s['text'].lower() for s in sources)
        hits+=int(passed)
        print(('PASS' if passed else 'FAIL'),prop,repr(q),'—',mode)
    print(f'Retrieval hit@4: {hits}/{len(cases)} on this fictional, five-question regression set.')
    print('This is not a claim of real-world accuracy or an automated hallucination evaluation.')
    if args.semantic and not retriever.status.startswith('hybrid'):
        raise SystemExit('Semantic evaluation did not run: model/dependency unavailable.')
    raise SystemExit(0 if hits==len(cases) else 1)
