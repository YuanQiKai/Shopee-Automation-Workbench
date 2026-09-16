import argparse,json,urllib.request
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--action',choices=['status','export'],default='status');p.add_argument('--output');a=p.parse_args()
url='http://127.0.0.1:3010/api/'+('export' if a.action=='export' else 'bootstrap')
with urllib.request.urlopen(url,timeout=20) as response:raw=response.read()
if a.action=='export':
    if not a.output:raise SystemExit('export requires --output')
    out=Path(a.output)
    if out.exists():raise SystemExit('Output exists; choose a new filename to preserve the previous review.')
    out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(raw);print(str(out))
else:
    d=json.loads(raw);print(json.dumps({'candidates':len(d['candidates']),'eligible':sum(c['evaluation']['eligible'] for c in d['candidates']),'supplier_count':len(d['suppliers']),'sku_count':sum(len(s['skus']) for s in d['suppliers']),'key_values':'not exported'},ensure_ascii=False))
