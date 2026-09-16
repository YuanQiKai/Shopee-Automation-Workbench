'use strict';
const researchEdits = new Map();
let researchSaveTimer, researchSaveNotice='', researchDraftsRestored=false;
const researchDraftKey=id=>'meeya-research-draft-v1:'+id;
const researchRequestId=()=>globalThis.crypto?.randomUUID?.()||('draft-'+Date.now()+'-'+Math.random().toString(36).slice(2));
function storedResearchDraft(id){return (researchData?.drafts||[]).find(d=>d.id===id);}
function persistLocalDraft(entry){
  try{localStorage.setItem(researchDraftKey(entry.id),JSON.stringify({id:entry.id,payload:entry.payload,draftRevision:entry.draftRevision,caseRevision:entry.caseRevision,requestId:entry.requestId}));return true;}
  catch{return false;}
}
function restoreResearchDrafts(){
  if(researchDraftsRestored)return; researchDraftsRestored=true;
  for(const c of researchData.cases){try{const value=JSON.parse(localStorage.getItem(researchDraftKey(c.id))||'null');if(value&&value.id===c.id&&value.payload){researchEdits.set(c.id,{...value,version:1,savedVersion:0,error:'检测到上次未完成的草稿，正在恢复',promise:null});}}catch{}}
  if(researchEdits.size)setTimeout(()=>{for(const entry of researchEdits.values())if(entry.version>entry.savedVersion&&!entry.blocked)saveResearchEntry(entry.id);},100);
}
function researchCaseForEditing(base){
  if(!base)return base;
  const stored=storedResearchDraft(base.id), edit=researchEdits.get(base.id);
  let c=clone(base);
  if(stored?.status==='draft')c={...c,...stored.payload};
  if(edit)c={...c,...edit.payload};
  c.assessment=clone(base.assessment);
  if(edit&&edit.version>edit.savedVersion)c.assessment={...c.assessment,state:'needs_evidence',label:'编辑中的草稿，等待核验',calculation:null,recommended:null,maxPurchasePerSaleCNY:null,stockCashUpperBound:null,scenarios:[],cash:null,canPublish:false,canPurchase:false,canReviewListing:false,selection:null};
  for(const key of ['quote','package','costs','checks','marketEvidence','demandEvidence','rulesEvidence','cashEvidence','checksEvidence'])if(!c[key]||typeof c[key]!=='object'||Array.isArray(c[key]))c[key]=clone(base[key]||{});
  if(!Array.isArray(c.comparisons))c.comparisons=[];
  return c;
}
function researchSaveIndicator(){
  const entry=researchEdits.get(researchCaseId),draft=storedResearchDraft(researchCaseId);
  return entry?.error|| (entry?.promise?'正在自动保存…':entry&&entry.version>entry.savedVersion?'修改已暂存，正在自动保存…':draft?.status==='draft'?'草稿已自动保存；'+draft.validationError:draft?'已自动保存 · '+localDate(draft.savedAt):'修改后自动保存；切换标签无需手动保存');
}
function updateResearchSaveIndicator(){const el=document.querySelector('#research-dirty');if(el)el.textContent=researchSaveIndicator();}
function updateResearchAssessmentOnly(){
  if(route!=='research'||researchTab!=='cases'||!document.createElement)return;
  const aside=document.querySelector('.research-case-grid > aside'); if(!aside)return;
  const template=document.createElement('template');template.innerHTML=caseResearchPage();
  const next=template.content?.querySelector('.research-case-grid > aside');if(next)aside.innerHTML=next.innerHTML;
  updateResearchSaveIndicator();
}
function captureResearchEdit(){
  const form=document.querySelector('#research-case-form');if(!form||route!=='research'||researchTab!=='cases')return null;
  const c=activeResearchCase();if(!c)return null;
  let entry=researchEdits.get(c.id);
  if(!entry){const before=clone(c),after=readForm(form,c);delete before.assessment;delete after.assessment;if(JSON.stringify(before)===JSON.stringify(after))return null;}
  if(!entry){entry={id:c.id,payload:null,caseRevision:researchData.cases.find(x=>x.id===c.id).revision,draftRevision:storedResearchDraft(c.id)?.revision||0,version:0,savedVersion:0,promise:null,error:'',requestId:null};researchEdits.set(c.id,entry);}
  const payload=readForm(form,c);delete payload.assessment;payload.revision=entry.caseRevision;
  if(JSON.stringify(entry.payload)!==JSON.stringify(payload)){entry.payload=payload;entry.version++;if(!entry.promise)entry.requestId=null;entry.error='';}
  researchDirty=entry.version>entry.savedVersion;
  persistLocalDraft(entry);updateResearchSaveIndicator();return entry;
}
function scheduleResearchSave(){
  const entry=captureResearchEdit();if(!entry)return;
  updateResearchAssessmentOnly();clearTimeout(researchSaveTimer);
  researchSaveTimer=setTimeout(()=>saveResearchEntry(entry.id),650);
}
async function saveResearchEntry(id){
  const entry=researchEdits.get(id);if(!entry)return true;
  if(entry.promise){await entry.promise;if(entry.version<=entry.savedVersion||entry.error)return !entry.error;}
  if(entry.version<=entry.savedVersion||entry.blocked)return !entry.error;
  const version=entry.version,payload=clone(entry.payload);
  const requestId=entry.requestId||researchRequestId();entry.requestId=requestId;
  persistLocalDraft(entry);
  entry.promise=(async()=>{
    let timeout,controller=typeof AbortController!=='undefined'?new AbortController():null;
    try{
      if(controller)timeout=setTimeout(()=>controller.abort(),8000);
      const response=await fetch('/api/research/cases/autosave',{method:'POST',headers:{'Content-Type':'application/json','X-MVP-Token':data.csrfToken},body:JSON.stringify({...payload,revision:entry.caseRevision,draftRevision:entry.draftRevision,requestId}),...(controller?{signal:controller.signal}:{})});
      const result=await response.json();
      if(!response.ok){if(response.status===409)entry.blocked=true;throw Error(result.error||'自动保存失败');}
      entry.caseRevision=result.case.revision;entry.draftRevision=result.draft.revision;
      entry.payload.revision=result.case.revision;entry.savedVersion=version;entry.error='';entry.requestId=null;
      const index=researchData.cases.findIndex(x=>x.id===id),prior=researchData.cases[index];
      if(index>=0)researchData.cases[index]={...result.case,assessment:prior.assessment};
      researchData.drafts=(researchData.drafts||[]).filter(d=>d.id!==id).concat(result.draft);
      if(entry.version===version){try{localStorage.removeItem(researchDraftKey(id));}catch{}}else persistLocalDraft(entry);
      await refreshResearch();
      researchSaveNotice='';
      return true;
    }catch(error){
      const local=persistLocalDraft(entry);
      entry.error=(entry.blocked?'版本冲突：':'自动保存暂未完成：')+error.message+(local?'；修改已暂存在本机':'；本机暂存也失败，请保持页面打开并复制修改');
      researchSaveNotice=entry.error;return false;
    }finally{clearTimeout(timeout);entry.promise=null;researchDirty=[...researchEdits.values()].some(x=>x.version>x.savedVersion);updateResearchSaveIndicator();updateResearchAssessmentOnly();}
  })();
  updateResearchSaveIndicator();const ok=await entry.promise;
  if(ok&&entry.version>entry.savedVersion)return saveResearchEntry(id);
  return ok;
}
async function flushResearchAutosave(){
  clearTimeout(researchSaveTimer);captureResearchEdit();
  for(const entry of researchEdits.values())if(entry.version>entry.savedVersion)await saveResearchEntry(entry.id);
  // Navigation remains available even offline; drafts and failures stay visible.
  return true;
}
document.addEventListener('input',e=>{if(e.target.closest?.('#research-case-form'))scheduleResearchSave();});
document.addEventListener('change',e=>{if(e.target.closest?.('#research-case-form'))scheduleResearchSave();});
window.addEventListener('beforeunload',()=>{captureResearchEdit();for(const e of researchEdits.values())if(e.version>e.savedVersion)persistLocalDraft(e);});
