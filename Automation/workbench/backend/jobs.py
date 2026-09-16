import asyncio,uuid,json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from temporalio import workflow,activity
from temporalio.common import RetryPolicy
from temporalio.client import Client
from temporalio.worker import Worker
with workflow.unsafe.imports_passed_through():
    from backend.db import Session,Record,put,now,read_all,PRIVATE
    from backend.domain import evaluate,ingest
    from backend.sorftime import SorftimeClient,ConnectorError,validate_query,MUTATING
    from backend.providers import decrypt
QUEUE='meeya-ph-selection'
def address():
    import os
    return os.environ.get('TEMPORAL_ADDRESS','127.0.0.1:7239')
@activity.defn
def run_job(job_id:str)->dict:
    with Session.begin() as s:
        row=s.get(Record,('job',job_id));job=dict(row.data);job.update(status='running',started_at=now());put(s,'job',job_id,job)
    try:
        if job['kind']=='recalculate':
            with Session.begin() as s:
                settings=s.get(Record,('settings','shop')).data;sups=[r.data for r in read_all(s,'supplier')];out=[]
                for c in read_all(s,'candidate'):
                    e=evaluate(c.data,settings,sups);out.append({'id':c.id,'eligible':e['eligible'],'missing':len(e['reasons'])})
                result={'checked':len(out),'eligible':sum(x['eligible'] for x in out),'rows':out}
        elif job['kind']=='sorftime':
            args=job['arguments'];tool=args['tool'];query=args['query']
            if tool in MUTATING or not tool.startswith(('shopee_','ali1688_')):raise ValueError('仅支持菲律宾和1688只读接口')
            validate_query(tool,query)
            with Session() as s:
                provider=s.get(Record,('provider',args['provider_id']))
                if not provider or provider.data.get('protocol')!='sorftime':raise ValueError('请先配置本地 Sorftime 密钥')
                key=decrypt(provider.data['secret'])
            raw=SorftimeClient(key).call(tool,query)
            snapshot={'id':str(uuid.uuid4()),'tool':tool,'arguments':query,'captured_at':now(),'source_type':'Sorftime第三方数据','result':raw}
            with Session.begin() as s:ingest(s,snapshot)
            result={'evidence_id':snapshot['id'],'message':'原始响应已保存；缺失/冲突字段未自动放行'}
        else:raise ValueError('任务类型无效')
        status='completed'
    except Exception as ex:
        result={'message':str(ex) if isinstance(ex,(ValueError,ConnectorError)) else '任务未完成；请检查连接配置或本地服务。未自动重试。'};status='failed'
    with Session.begin() as s:
        r=s.get(Record,('job',job_id));put(s,'job',job_id,{**r.data,'status':status,'finished_at':now(),'result':result})
    return {'status':status,'result':result}
@workflow.defn
class ResearchWorkflow:
    @workflow.run
    async def run(self,job_id:str)->dict:
        return await workflow.execute_activity(run_job,job_id,start_to_close_timeout=timedelta(minutes=4),retry_policy=RetryPolicy(maximum_attempts=1))
async def serve():
    client=await Client.connect(address())
    worker=Worker(client,task_queue=QUEUE,workflows=[ResearchWorkflow],activities=[run_job],activity_executor=ThreadPoolExecutor(max_workers=2))
    await worker.run()
if __name__=='__main__':asyncio.run(serve())
