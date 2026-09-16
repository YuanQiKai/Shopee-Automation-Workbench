import sys,json,copy
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R))
from backend.db import Session,Record,put,audit
from backend.domain import ingest
snaps=json.loads((R/'data/evidence/sorftime-refresh-2026-09-15.json').read_text(encoding='utf-8'))
with Session.begin() as s:
    for snap in snaps:
        if 'result' in snap and not s.get(Record,('evidence',snap['id'])):ingest(s,snap)
    r=s.get(Record,('candidate','C01'));c=copy.deepcopy(r.data)
    if not c.get('primary') and not c.get('backup'):
        c['primary']={'offer_id':'625255182969','sku_id':'4437596177689','verification':{},'note':'候选细网大中小3件套；报价与规格仍待确认'}
        c['backup']={'offer_id':'705110577312','sku_id':'','verification':{},'note':'备用商家只给单袋SKU；须匹配30x40、40x50、50x60三件组合，不能拿一只袋子的价格代替套装'}
        c['fact'] += '；2026-09-15 Sorftime已取得两商家具体SKU及库存快照，主候选细网3件套展示4.9/报价字段5.0元；备用商家仅单袋SKU，尚未同规格核定。'
        put(s,'candidate','C01',c);audit(s,'补充真实货源候选','C01',{'primary_offer':'625255182969','backup_offer':'705110577312','approval':'仍待补证'})
print('Updated fresh evidence and retained primary/backup supplier candidates; no candidate approved.')
