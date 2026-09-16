'use strict';
const researchProductTools=new Set(['shopee_product_search','shopee_product_search_from_name','shopee_product_request','shopee_keyword_relation_results','ali1688_product_search','ali1688_similar_product','ali1688_product_search_from_image','ali1688_product_request','ali1688_product_variations']);
async function runResearchQuery(tool,args,batchId,options={}){
  if(researchBusy)throw Error('已有接口请求正在执行，请等待返回');
  await flushResearchAutosave();researchBusy=true;
  try{
    const body={tool,args,batchId};if(options.confirmedExternalChange)Object.assign(body,{confirmedExternalChange:true,requestId:options.requestId});
    const result=await(await api('/api/research/query',body)).json();
    toast('请求已发出，正在获取 Sorftime 真实返回数据');await refreshResearch();renderResearch();
    for(let i=0;i<120;i++){
      await new Promise(resolve=>setTimeout(resolve,1200));await refreshResearch();
      const job=researchData.jobs.find(j=>j.id===result.job.id);
      if(job&&['completed','quarantined','failed','interrupted'].includes(job.status)){
        if(job.status!=='completed'){renderResearch();throw Error(job.error||'接口没有返回可用结果；未自动重试');}
        if(researchProductTools.has(tool)){
          const key=tool==='ali1688_product_variations'?'sku':tool.startsWith('ali1688_')?'supply':'market';
          researchPaging[key].snapshot=job.snapshotId;researchPaging[key].page=1;
          if(options.showResult!==false)researchTab=key==='sku'?'supply':key;
          renderResearch(true);
        }else await showResearchSnapshot(job.snapshotId);
        toast('真实响应已保存；展示分页不会再调用接口');return job.batchId;
      }
    }
    throw Error('等待超时，请查看采集记录；不要直接重复发送请求');
  }finally{researchBusy=false;renderResearch();}
}
function prepareResearchExternal(request){
  researchPendingExternal={...request,requestId:researchRequestId()};
  showModal('确认修改 Sorftime 关键词收藏',`<p class="callout">将执行：${esc(researchToolLabels[request.tool]||request.tool)}。这会修改 Sorftime 账号数据，不是仅查看本机页面。</p>${researchRawValue(request.args)}<div class="form-actions"><button type="button" class="button" data-action="close-modal">取消</button><button type="button" class="button primary" data-ra="confirm-external">确认执行这次变更</button></div>`);
}
document.addEventListener('click',async e=>{
  const button=e.target.closest?.('[data-ra]');if(!button||button.disabled)return;
  const action=button.dataset.ra,id=button.dataset.id;
  try{
    if(action==='confirm-external'){
      if(!researchPendingExternal)throw Error('确认内容已失效，请重新选择操作');
      const request=researchPendingExternal;researchPendingExternal=null;button.disabled=true;$('#modal').close();
      await runResearchQuery(request.tool,request.args,undefined,{confirmedExternalChange:true,requestId:request.requestId});return;
    }
    await flushResearchAutosave();
    if(action==='tab'){researchTab=id;renderResearch(true);}
    else if(action==='connection'){researchTab='connection';renderResearch(true);}
    else if(action==='page'){const key=button.dataset.key;const n=Number(id);if(researchPaging[key]&&Number.isInteger(n)&&n>=1){researchPaging[key].page=n;renderResearch(true);document.querySelector('.research-scroll')?.scrollTo?.({top:0});}}
    else if(action==='raw-detail')await showResearchObservation(id);
    else if(action==='snapshot-view')await showResearchSnapshot(id);
    else if(action==='select-tool'){researchQueryDrafts.tool={tool:id,values:id.startsWith('shopee_')?{site:'PH'}:{}};researchTab='tools';renderResearch(true);}
    else if(action==='new-case'){const r=await(await api('/api/research/cases',{observationId:id})).json();researchCaseId=r.case.id;researchTab='cases';await refreshResearch();renderResearch(true);}
    else if(action==='market-detail'){const row=researchData.observations.find(o=>o.id===id);await runResearchQuery('shopee_product_request',{site:'PH',product_id:row.sourceId});}
    else if(action==='supplier-detail'){const row=researchData.observations.find(o=>o.id===id);const batch=await runResearchQuery('ali1688_product_request',{product_id:row.sourceId},undefined,{showResult:false});await runResearchQuery('ali1688_product_variations',{product_id:row.sourceId},batch);}
    else if(action==='add-comparison'){
      const c=activeResearchCase();if(!c)throw Error('请先选择要加入竞品的候选');const row=researchData.observations.find(o=>o.id===id);
      if(c.comparisons.some(x=>researchData.observations.find(o=>o.id===x.observationId)?.identity===row.identity))throw Error('该来源商品已经在竞品列表中');
      const next=clone(c);next.comparisons.push({observationId:id,sameSpec:'unknown',arrivalPricePHP:'',specEvidence:'',source:'',validUntil:''});
      await saveResearchProgrammatic(next);renderResearch(true);toast('已自动保存到竞品列表，同规格和到手价仍需核实');
    }
    else if(action==='remove-comparison'){const c=clone(activeResearchCase());c.comparisons.splice(Number(id),1);await saveResearchProgrammatic(c);renderResearch(true);}
    else if(action==='download-needs'){const c=activeResearchCase();download(new Blob([c.title+'\n'+c.assessment.label+'\n\n'+c.assessment.needs.map((n,i)=>`${i+1}. [${n.section}] ${n.message}`).join('\n')+'\n\n不通过：\n'+c.assessment.failures.join('\n')],{type:'text/plain;charset=utf-8'}),'needs-evidence.txt');}
    else if(action==='export-case'){if(researchEdits.get(id)?.error)throw Error('该候选尚有未完成的自动保存，不能导出旧版本冒充当前修改');download(await(await api('/api/research/export/'+id)).blob(),'research-case.json');}
    else if(action==='retry-autosave'){for(const entry of researchEdits.values())if(!entry.blocked){entry.error='';await saveResearchEntry(entry.id);}renderResearch(true);}
    else if(action==='recover-draft'){
      const entry=researchEdits.get(id);if(!entry)throw Error('没有待恢复的本机草稿');
      showModal('保留草稿并继续编辑',`<p>先下载你在本机的这份完整草稿，再载入服务器较新版本。不会覆盖服务器资料；冲突副本仍在恢复记录中。</p>${researchRawValue(entry.payload)}<button type="button" class="button primary spaced" data-ra="download-and-reload-draft" data-id="${esc(id)}">下载这份草稿，再载入已保存版本</button>`);
    }
    else if(action==='download-and-reload-draft'){
      const entry=researchEdits.get(id);if(!entry)throw Error('本机草稿已处理');
      download(new Blob([JSON.stringify({caseId:id,payload:entry.payload,meaning:'自动保存冲突恢复副本，不是已核实采购或上架资料'},null,2)],{type:'application/json'}),'research-draft-recovery.json');
      await refreshResearch();researchEdits.delete(id);try{localStorage.removeItem(researchDraftKey(id));}catch{}
      researchSaveNotice='';researchCaseId=id;researchTab='cases';$('#modal').close();renderResearch(true);toast('已载入已保存版本；本机修改保存在刚下载的恢复文件中');
    }
  }catch(error){toast(error.message,true);}
});
async function saveResearchProgrammatic(c){
  let entry=researchEdits.get(c.id);if(!entry){entry={id:c.id,caseRevision:c.revision,draftRevision:storedResearchDraft(c.id)?.revision||0,version:0,savedVersion:0,promise:null,error:'',requestId:null};researchEdits.set(c.id,entry);}
  entry.payload=clone(c);delete entry.payload.assessment;entry.version++;entry.requestId=null;persistLocalDraft(entry);await saveResearchEntry(c.id);
}
document.addEventListener('submit',async e=>{
  const form=e.target;
  if(!['research-api-form','research-connect-form','research-case-form','research-import-form','research-policy-form'].includes(form.id))return;
  e.preventDefault();const button=form.querySelector('button[type="submit"]');if(button)button.disabled=true;
  try{
    if(form.id==='research-api-form'){const request=captureResearchQuery(form);if(researchSpec(request.tool)?.mutating)prepareResearchExternal(request);else await runResearchQuery(request.tool,request.args);}
    else if(form.id==='research-policy-form'){await flushResearchAutosave();await api('/api/research/policy',{revision:researchData.policy.revision,maxSellingPricePHP:form.elements.maxSellingPricePHP.value});await refreshResearch();renderResearch(true);toast('成交价上限已更新，未知币种不会自动套用');}
    else if(form.id==='research-connect-form'){const key=form.elements.key.value.trim();form.elements.key.value='';if(!key&&!researchData.connector.configured)throw Error('请在本机输入密钥');await api('/api/research/connect',key?{key}:{});await refreshResearch();renderResearch(true);toast('已核对账号实际可用的 Shopee / 1688 工具目录');}
    else if(form.id==='research-case-form'){await flushResearchAutosave();updateResearchAssessmentOnly();}
    else if(form.id==='research-import-form'){const file=form.elements.file.files[0];if(!file||file.size>7000000)throw Error('请选择 7MB 以内的原始 JSON 快照');await api('/api/research/import',JSON.parse(await file.text()));await refreshResearch();renderResearch(true);toast('已保留原始响应，来源明确标为人工导入');}
  }catch(error){toast(error.message,true);}finally{if(button)button.disabled=false;}
});
document.addEventListener('input',e=>{const form=e.target.closest?.('#research-api-form');if(form)captureResearchQuery(form);});
document.addEventListener('change',async e=>{
  const target=e.target;
  try{
    if(target.dataset.pageSize){researchPaging[target.dataset.pageSize].size=Number(target.value);researchPaging[target.dataset.pageSize].page=1;renderResearch(true);}
    else if(target.dataset.resultBatch){researchPaging[target.dataset.resultBatch].snapshot=target.value;researchPaging[target.dataset.resultBatch].page=1;renderResearch(true);}
    else if(target.id==='research-query-tool'){const key=target.dataset.queryKey;researchQueryDrafts[key]={tool:target.value,values:target.value.startsWith('shopee_')?{site:'PH',page:1}:{page:1}};renderResearch(true);}
    else if(['research-case-picker','research-compare-case'].includes(target.id)){const next=target.value;await flushResearchAutosave();researchCaseId=next;renderResearch(true);}
  }catch(error){toast(error.message,true);}
});
