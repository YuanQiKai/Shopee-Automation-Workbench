// Isolated view/interaction contracts. No browser automation or business writes.
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const catalog=JSON.parse(fs.readFileSync(path.join(__dirname,'sorftime_catalog.json'),'utf8')).tools;
let checks=0;
function harness(){
  const storage=new Map(),listeners={};let visible=false;
  const field={name:'title',value:'Synthetic changed',type:'text',dataset:{}};
  const form={querySelectorAll:()=>[field]};
  const placeholder={addEventListener(){},close(){},classList:{add(){},remove(){}},innerHTML:'',textContent:''};
  const document={querySelector:s=>s==='#research-case-form'?(visible?form:null):placeholder,querySelectorAll:()=>[],addEventListener:(event,fn)=>(listeners[event]||=[]).push(fn)};
  const sandbox={document,window:{addEventListener(){},scrollTo(){}},URL,Blob,Intl,console,setTimeout,clearTimeout,AbortController,
    localStorage:{setItem:(k,v)=>storage.set(k,v),getItem:k=>storage.get(k)||null,removeItem:k=>storage.delete(k)},
    fetch:async()=>{throw Error('Network is not permitted in synthetic UI tests');},catalog};
  const context=vm.createContext(sandbox),run=code=>vm.runInContext(code,context);
  for(const file of ['research.js','research-autosave.js','research-browser.js','research-interactions.js','app.js']){
    let source=fs.readFileSync(path.join(__dirname,'static',file),'utf8');if(file==='app.js')source=source.replace(/start\(\);\s*$/,'');
    vm.runInContext(source,context,{filename:file});
  }
  run(`data={csrfToken:'SYNTHETIC'};researchData={connector:{catalog,supportedTools:[]},observations:[],snapshots:[],cases:[{id:'synthetic',title:'Original',revision:1,quote:{},package:{},costs:{},checks:{},comparisons:[],assessment:{state:'needs_evidence',label:'Synthetic',needs:[],failures:[],warnings:[],calculation:{profit:'OLD'},cash:{required:'OLD'}}}],drafts:[],conflictDrafts:[]};researchCaseId='synthetic';route='research';researchTab='cases';refreshResearch=async()=>{};render=()=>{};`);
  return {context,run,storage,field,listeners,showForm:()=>{visible=true;}};
}
async function check(name,fn){await fn();checks++;console.log('PASS '+name);}
async function main(){
  await check('10/20/50/100 pagination, empty lists, clamp, full remainder',()=>{
    const h=harness();
    for(const key of ['market','supply','sku','tool'])for(const size of [10,20,50,100]){
      const result=h.run(`researchPaging.${key}.size=${size};researchPaging.${key}.page=999;researchPageSlice(Array.from({length:201},(_,i)=>i),'${key}')`);
      assert.equal(result.page,Math.ceil(201/size));assert.equal(result.items.length,1);assert.equal(result.items[0],200);
      assert.equal(h.run(`researchPageSlice([],'${key}').page`),1);
    }
  });
  await check('pagination events never request Sorftime',async()=>{
    const h=harness();let calls=0;h.context.fetch=async()=>{calls++;throw Error('unexpected');};
    for(const listener of h.listeners.click)await listener({target:{closest:s=>s==='[data-ra]'?{disabled:false,dataset:{ra:'page',key:'market',id:'2'}}:null}});
    assert.equal(h.run('researchPaging.market.page'),2);assert.equal(calls,0);
  });
  await check('every request parameter is exposed; obsolete local filters absent',()=>{
    const h=harness();
    for(const spec of catalog){
      const html=h.run(`researchQueryDrafts.tool={tool:${JSON.stringify(spec.name)},values:{}};researchApiForm('tool')`);
      for(const key of Object.keys(spec.inputSchema.properties))assert.ok(html.includes(`name="${key}"`),spec.name+'.'+key);
      assert.ok(!html.includes('research-search'));assert.ok(!html.includes('research-group'));
    }
  });
  await check('parameter serializer preserves zero and does not send blank optional fields',()=>{
    const h=harness();h.context.form={dataset:{queryKey:'market'},elements:{namedItem:name=>({value:({site:'PH',page:'1',price_range_min:'0',price_range_max:''})[name]??''})}};
    const result=h.run('captureResearchQuery(form)');
    assert.deepEqual(JSON.parse(JSON.stringify(result.args)),{site:'PH',page:1,price_range_min:0});
  });
  await check('images use exact allowed source; arbitrary hosts and scripts rejected',()=>{
    const h=harness();
    for(const url of ['https://down-ph.img.susercontent.com/real','https://cbu01.alicdn.com/real'])assert.equal(h.run(`safeResearchImage(${JSON.stringify(url)})`),url);
    for(const url of ['javascript:alert(1)','https://alicdn.com.evil.test/x','http://cbu01.alicdn.com/x','https://secret:pw@cbu01.alicdn.com/x'])assert.equal(h.run(`safeResearchImage(${JSON.stringify(url)})`),'');
    const html=h.run(`researchThumb({id:'1',title:'<script>long</script>',photos:['https://cbu01.alicdn.com/real']})`);
    assert.ok(html.includes('loading="lazy"'));assert.ok(html.includes('&lt;script&gt;'));assert.ok(!html.includes('<script>'));
  });
  await check('long-title clipping preserves full text in accessible detail button',()=>{
    const h=harness();h.context.longTitle='Synthetic '+('long title '.repeat(200))+'<script>';
    const html=h.run(`researchTitleCell({id:'1',sourceId:'123',title:longTitle})`);
    assert.ok(html.includes('research-title-button'));assert.ok(html.includes('&lt;script&gt;'));assert.ok(html.includes('data-ra="raw-detail"'));
    const css=fs.readFileSync(path.join(__dirname,'static/research.css'),'utf8');
    assert.ok(css.includes('-webkit-line-clamp:2'));assert.ok(css.includes('20 * var(--research-row-height)'));assert.ok(css.includes('table-layout:fixed'));
  });
  await check('all raw nested fields preserve zero, false, null and long values',()=>{
    const h=harness();const long='Z'.repeat(15000);h.context.payload={novel:{zero:0,false:false,nil:null,text:long,unsafe:'<img onerror=x>'}};
    const html=h.run('researchRawValue(payload)');for(const text of ['novel.zero','novel.false','null（原始返回）',long,'&lt;img onerror=x&gt;'])assert.ok(html.includes(text));
  });
  await check('nested data.products has local pagination and retains envelope fields',()=>{
    const h=harness();h.context.payload={doc:{'products.price':'THB',page_count:'All pages'},data:{page:1,page_count:299,products:Array.from({length:55},(_,i)=>({product_id:String(i),title:'Item '+i,price:30}))}};
    const html=h.run(`researchPaging.tool.size=20;researchToolPayload(payload)`);
    assert.ok(html.includes('page_count'));assert.ok(html.includes('299'));assert.ok(html.includes('THB'));assert.ok(html.includes('Item 19'));assert.ok(!html.includes('Item 20'));
  });
  await check('empty query batches remain selectable',()=>{
    const h=harness();h.run(`researchData.snapshots=[{id:'empty',tool:'shopee_product_search',args:{site:'PH'},fetchedAt:'2026-09-01T00:00:00Z',resultInfo:{page:1,pageCount:1,returnedRows:0}}];researchPaging.market.snapshot='empty'`);
    const html=h.run(`researchBatchPicker('market')`);assert.ok(html.includes('value="empty" selected'));assert.ok(html.includes('返回 0 条'));
  });
  await check('automatic save is triggered without any manual save click',async()=>{
    const h=harness();h.showForm();let calls=0;
    h.context.fetch=async(_,options)=>{calls++;const b=JSON.parse(options.body);return {ok:true,json:async()=>({case:{...b,revision:2},draft:{id:b.id,revision:1,status:'committed',payload:b}})};};
    await h.run('flushResearchAutosave()');assert.equal(calls,1);assert.equal(h.run(`researchEdits.get('synthetic').savedVersion`),1);assert.equal(h.storage.size,0);
  });
  await check('unchanged form navigation does not create a save request',async()=>{
    const h=harness();h.showForm();h.field.value='Original';let calls=0;h.context.fetch=async()=>{calls++;throw Error('unexpected');};
    await h.run('flushResearchAutosave()');assert.equal(calls,0);assert.equal(h.run('researchEdits.size'),0);
  });
  await check('edits made during in-flight save are saved in order',async()=>{
    const h=harness();h.showForm();const requests=[];let release;
    h.context.fetch=async(_,options)=>{const b=JSON.parse(options.body);requests.push(b);if(requests.length===1)await new Promise(resolve=>{release=resolve;});return {ok:true,json:async()=>({case:{...b,revision:b.revision+1},draft:{id:b.id,revision:b.draftRevision+1,status:'committed',payload:b}})};};
    h.run('captureResearchEdit()');const saving=h.run(`saveResearchEntry('synthetic')`);
    h.field.value='Newest edit';h.run('captureResearchEdit()');release();await saving;
    assert.equal(requests.length,2);assert.equal(requests[1].title,'Newest edit');assert.equal(requests[1].revision,2);assert.equal(requests[1].draftRevision,1);
    assert.notEqual(requests[0].requestId,requests[1].requestId);assert.equal(h.storage.size,0);
  });
  await check('offline navigation proceeds while local recovery and warning stay',async()=>{
    const h=harness();h.showForm();await h.run(`go('dashboard')`);
    assert.equal(h.run('route'),'dashboard');assert.ok(h.storage.size>0);assert.ok(h.run('researchSaveNotice').includes('暂未完成'));
    assert.equal(h.run(`researchCaseForEditing(researchData.cases[0]).assessment.calculation`),null);
  });
  await check('conflict cannot overwrite newer server version',async()=>{
    const h=harness();h.showForm();let calls=0;h.context.fetch=async()=>{calls++;return {ok:false,status:409,json:async()=>({error:'conflict saved separately'})};};
    await h.run('flushResearchAutosave()');await h.run('flushResearchAutosave()');
    assert.equal(calls,1);assert.ok(h.run(`researchEdits.get('synthetic').blocked`));assert.ok(h.storage.size>0);
  });
  await check('server-side incomplete draft is merged into editable form',()=>{
    const h=harness();h.run(`researchData.drafts=[{id:'synthetic',status:'draft',revision:1,payload:{title:'Saved incomplete',quote:{unitPrice:'-'}}}]`);
    const c=h.run('activeResearchCase()');assert.equal(c.title,'Saved incomplete');assert.equal(c.quote.unitPrice,'-');
  });
  await check('pending local draft is restored only for known candidates',()=>{
    const h=harness();h.storage.set('meeya-research-draft-v1:synthetic',JSON.stringify({id:'synthetic',payload:{title:'Recovered'},caseRevision:1,draftRevision:0}));
    h.run('restoreResearchDrafts()');assert.equal(h.run('activeResearchCase().title'),'Recovered');assert.equal(h.run('activeResearchCase().assessment.calculation'),null);
  });
  await check('three mutating tools display explicit per-operation confirmation',()=>{
    const h=harness();let html='';h.context.captureModal=body=>{html=body;};h.run('showModal=(_,body)=>captureModal(body)');
    for(const tool of catalog.filter(t=>t.mutating)){
      h.run(`prepareResearchExternal({tool:${JSON.stringify(tool.name)},args:{site:'PH',keyword:'Synthetic'}})`);
      assert.ok(html.includes('data-ra="confirm-external"'));assert.ok(html.includes('Synthetic'));assert.ok(html.includes('修改 Sorftime 账号数据'));
    }
  });
  console.log(`${checks} v0.3 UI contracts passed. No browser or external provider used.`);
}
main().catch(error=>{console.error(error);process.exitCode=1;});
