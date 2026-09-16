import json,uuid,copy
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import JSONResponse,Response
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select,text
from temporalio.client import Client
from .db import Base,engine,Session,Record,Audit,put,read_all,audit,now,ROOT
from .domain import seed,evaluate,supplier_view,GATES,ingest
from .costs import RATES,EXTRAS,dec,D,compute
from .providers import PRESETS,encrypt,public_config,validate_endpoint,generate
from .export import workbook
from .jobs import ResearchWorkflow,QUEUE,address
from .sorftime import SPECS,MUTATING,validate_query
app=FastAPI(title='Meeya 菲律宾审核工作台',version='0.4.0')
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','testserver'])
@app.middleware('http')
async def local_boundary(request:Request,call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        if origin not in ('http://127.0.0.1:3010','http://localhost:3010','http://127.0.0.1:8010') or request.headers.get('x-meeya-local')!='1':return JSONResponse({'detail':'请从本地工作台提交操作'},status_code=403)
    response=await call_next(request);response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff';return response
@app.exception_handler(ValueError)
async def invalid(request,ex):return JSONResponse({'detail':str(ex)},status_code=422)
@app.on_event('startup')
def startup():
    Base.metadata.create_all(engine)
    with Session.begin() as s:seed(s)
def pack(r):return {'id':r.id,'revision':r.revision,'updated_at':r.updated_at.isoformat() if r.updated_at else now(),'data':r.data}
def settings_row(s,lock=False):
    q=select(Record).where(Record.kind=='settings',Record.id=='shop')
    return s.scalar(q.with_for_update() if lock else q)
def all_suppliers(s):return [copy.deepcopy(r.data) for r in read_all(s,'supplier')]
@app.get('/api/health')
def health():
    with Session() as s:s.execute(text('SELECT 1'))
    return {'status':'ok','database':'PostgreSQL','queue':'Temporal','scope':'PH','local':True}
@app.get('/api/bootstrap')
def bootstrap():
    with Session() as s:
        setting=settings_row(s);sups=all_suppliers(s)
        candidates=[{**pack(c),'evaluation':evaluate(c.data,setting.data,sups)} for c in read_all(s,'candidate')]
        return {'candidates':candidates,'settings':pack(setting),'suppliers':[supplier_view(x) for x in sups],'sources':RATES['sources'],'rules_version':RATES['version'],'sea_ban_count':len(RATES['sea_ban']),'gates':GATES,'providers':[public_config(r.data) for r in read_all(s,'provider')],'provider_presets':PRESETS,'jobs':[pack(r) for r in read_all(s,'job')][-30:],'evidence':[{'id':r.id,'tool':r.data['tool'],'arguments':r.data['arguments'],'captured_at':r.data.get('captured_at'),'captured_date':r.data.get('captured_date')} for r in read_all(s,'evidence')],'connectors':[{'name':'Amazon SP-API','status':'规划中'},{'name':'Amazon Ads API','status':'规划中'},{'name':'ERP API','status':'规划中'},{'name':'汇率 API','status':'手动录入可用，自动连接待配置'}]}
class Change(BaseModel):
    revision:int
    data:dict[str,Any]
    model_config=ConfigDict(extra='forbid')
@app.put('/api/settings')
def save_settings(body:Change):
    allowed=set(json.loads((ROOT/'data/default-settings.json').read_text(encoding='utf-8')))
    if set(body.data)-allowed:raise ValueError('配置包含未知字段')
    for k,v in body.data.items():
        if k.endswith(('_cny','_pct')) or k in ('activity_factor','fx_cny_per_php'):dec(v)
    for k in ('commission_pct','transaction_pct','program_pct'):
        if dec(body.data.get(k)) is not None and dec(body.data[k])>100:raise ValueError('费率不得超过100%')
    if body.data.get('withdrawal_pct','0.2')!='0.2':raise ValueError('本版提现率按用户确认0.2%；如变化先更新规则')
    with Session.begin() as s:
        r=settings_row(s,True)
        if r.revision!=body.revision:raise HTTPException(409,'配置已被更新，请重新载入')
        merged={**r.data,**body.data};put(s,'settings','shop',merged);audit(s,'保存经营配置','shop',{'revision':r.revision,'changed_fields':list(body.data)})
    return {'ok':True}
@app.post('/api/candidates')
def create_candidate(body:dict):
    name=str(body.get('name','')).strip()
    if not name or len(name)>200:raise ValueError('请输入200字以内产品名称')
    id='N'+uuid.uuid4().hex[:8]
    data={'id':id,'name':name,'spec':body.get('spec',''),'priority':'待调研','fact':'用户新建候选，暂无市场证据','inference':'','recommendation':'补齐市场、主备货源和成本后审核','evidence_rows':[],'checks':{},'financial':{'channel':'standard'},'review':{'state':'pending'},'category_ids':[],'market_observations':[]}
    with Session.begin() as s:put(s,'candidate',id,data);audit(s,'新建候选',id,{})
    return {'id':id}
@app.put('/api/candidates/{id}')
def save_candidate(id:str,body:Change):
    allowed={'name','spec','priority','financial','checks','category_ids','primary','backup','market_url','market_observations','planned_landed_php','difference_evidence','fact','inference','recommendation','difference'}
    if set(body.data)-allowed:raise ValueError('包含不可编辑字段')
    if len(json.dumps(body.data))>2000000:raise ValueError('候选数据过大')
    with Session.begin() as s:
        st=settings_row(s,True);r=s.get(Record,('candidate',id))
        if not r:raise HTTPException(404,'候选不存在')
        if r.revision!=body.revision:raise HTTPException(409,'候选已更新，请重新载入')
        merged={**r.data,**body.data};compute(merged,st.data)
        if merged.get('review',{}).get('state')=='approved':merged['review']={**merged['review'],'state':'stale'}
        put(s,'candidate',id,merged);audit(s,'保存候选',id,{'changed_fields':list(body.data),'revision':r.revision})
    return {'ok':True}
@app.post('/api/candidates/{id}/review')
def review(id:str,body:dict):
    state=body.get('state');note=str(body.get('note','')).strip()
    if state not in ('approved','rejected','pending'):raise ValueError('审核状态无效')
    if not note:raise ValueError('请填写审核理由')
    with Session.begin() as s:
        st=settings_row(s,True);r=s.get(Record,('candidate',id))
        if not r:raise HTTPException(404,'候选不存在')
        if body.get('revision')!=r.revision:raise HTTPException(409,'候选版本已变化')
        sups=all_suppliers(s);ev=evaluate(r.data,st.data,sups)
        if state=='approved':
            if not ev['eligible']:raise HTTPException(422,{'message':'关键证据/利润未通过','reasons':ev['reasons']})
            others=[x.data for x in read_all(s,'candidate') if x.id!=id and x.data.get('review',{}).get('state') in ('approved','stale')]
            reserved=sum((dec(x['review'].get('reserved_cny')) or D(0) for x in others),D(0))
            needed=dec(ev['base']['cash_needed_cny']);test=dec(ev['base']['test_total_cny'])
            available=max(D(0),dec(st.data['available_cash_cny'])-dec(st.data['commitments_cny'])-dec(st.data['reserve_cny']))*D('.8')-reserved
            loss_room=dec(st.data['monthly_loss_limit_cny'])-dec(st.data['realized_loss_cny'])-dec(st.data['unresolved_loss_cny'])-reserved
            if needed>available or needed>loss_room:raise HTTPException(422,'全店现金或月亏损容量不足；已合并其他批准/失效但未释放的测试承诺')
        else:needed=D(0)
        c={**r.data,'review':{'state':state,'note':note,'at':now(),'input_hash':ev['input_hash'],'reserved_cny':str(needed)}}
        put(s,'candidate',id,c);audit(s,'人工审核',id,c['review'])
    return {'ok':True}
@app.get('/api/evidence/{id}')
def evidence_detail(id:str):
    with Session() as s:
        r=s.get(Record,('evidence',id))
        if not r:raise HTTPException(404,'证据不存在')
        return r.data
@app.get('/api/sea-ban')
def sea_ban(q:str=''):return [b for b in RATES['sea_ban'] if q in b['path'] or q in b['category_id']]
@app.get('/api/audit')
def audit_rows():
    with Session() as s:return [{'id':r.id,'at':r.at.isoformat(),'action':r.action,'target':r.target,'detail':r.detail} for r in s.scalars(select(Audit).order_by(Audit.id.desc()).limit(100))]
@app.post('/api/providers')
def save_provider(body:dict):
    protocol=body.get('protocol')
    if protocol not in ('openai','anthropic','gemini','sorftime'):raise ValueError('不支持此协议')
    name=str(body.get('name','')).strip();pid=str(body.get('id') or uuid.uuid4())
    if not name or len(name)>100:raise ValueError('连接名称无效')
    base='https://mcp.sorftime.com' if protocol=='sorftime' else validate_endpoint(str(body.get('base_url','')))
    with Session.begin() as s:
        old=s.get(Record,('provider',pid));key=body.get('api_key')
        if not key and not old:raise ValueError('请在本机输入密钥')
        data={'id':pid,'name':name,'protocol':protocol,'base_url':base,'model':str(body.get('model','')),'secret':encrypt(key) if key else old.data['secret']}
        put(s,'provider',pid,data);audit(s,'保存API连接',pid,{'name':name,'protocol':protocol,'has_key':True})
    return public_config(data)
@app.post('/api/ai-summary')
def ai_summary(body:dict):
    if body.get('confirm_external_and_cost') is not True:raise HTTPException(422,'需明确确认将当前产品证据发送到所选服务，可能产生API费用')
    with Session() as s:
        p=s.get(Record,('provider',body.get('provider_id')));c=s.get(Record,('candidate',body.get('candidate_id')))
        if not p or not c:raise ValueError('连接或产品不存在')
        payload={k:c.data.get(k) for k in ('name','spec','fact','inference','evidence_rows')};config=p.data;rev=c.revision
    summary=generate(config,payload)
    with Session.begin() as s:
        c=s.get(Record,('candidate',body['candidate_id']))
        if c.revision!=rev:raise HTTPException(409,'生成期间产品发生变化，摘要未保存，请重试时重新确认')
        put(s,'candidate',c.id,{**c.data,'ai_summary':{'text':summary,'provider':config['name'],'at':now(),'label':'AI解释，不能替代证据/硬门槛'}});audit(s,'AI摘要',c.id,{'provider':config['name']})
    return {'summary':summary}
@app.get('/api/tools')
def tools_catalog():return [v for k,v in SPECS.items() if k not in MUTATING and k.startswith(('shopee_','ali1688_'))]
@app.post('/api/jobs')
async def enqueue(body:dict):
    kind=body.get('kind')
    if kind not in ('recalculate','sorftime'):raise ValueError('任务类型无效')
    args=body.get('arguments',{})
    if kind=='sorftime':
        if args.get('tool') in MUTATING:raise ValueError('禁止外部写操作')
        validate_query(args.get('tool'),args.get('query'))
    id=str(uuid.uuid4());job={'id':id,'kind':kind,'arguments':args,'status':'queued','created_at':now()}
    with Session.begin() as s:put(s,'job',id,job);audit(s,'提交本地任务',id,{'kind':kind})
    try:
        client=await Client.connect(address());await client.start_workflow(ResearchWorkflow.run,id,id=id,task_queue=QUEUE)
    except Exception:
        with Session.begin() as s:put(s,'job',id,{**job,'status':'failed','result':{'message':'Temporal未就绪，未执行也未自动重试'}})
        raise HTTPException(503,'任务队列未连接，请运行启动工作台')
    return {'id':id}
@app.get('/api/export')
def export_xlsx():
    with Session() as s:
        cs=[r.data for r in read_all(s,'candidate')];st=settings_row(s).data;sups=[supplier_view(x) for x in all_suppliers(s)];ev={c['id']:evaluate(c,st,sups) for c in cs};data=workbook(cs,st,sups,[r.data for r in read_all(s,'evidence')],ev)
    return Response(data,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename="Meeya-PH-selection.xlsx"'})
