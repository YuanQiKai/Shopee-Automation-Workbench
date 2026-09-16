// Read-only view-function smoke checks. This is not a browser or visual test.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const base = process.argv[2] || 'http://127.0.0.1:8765';
const elements = new Map();
const listeners = {};
function element(selector) {
  if (!elements.has(selector)) elements.set(selector, {innerHTML:'', textContent:'', className:'', style:{}, dataset:{}, classList:{add(){},remove(){}}, addEventListener(){},showModal(){},close(){}});
  return elements.get(selector);
}
const document = {querySelector:element, querySelectorAll:()=>[], addEventListener:(event, fn)=>{listeners[event]=fn;}};
const context = vm.createContext({document, window:{scrollTo(){},addEventListener(){}}, console, Intl, Date, Set, URL, Blob, setTimeout, clearTimeout,
  fetch:(route, options)=>fetch(new URL(route, base), options)});
async function run() {
  let source = fs.readFileSync(path.join(__dirname, 'static/app.js'), 'utf8');
  source = source.replace(/start\(\);\s*$/, '');
  for (const file of ['research.js','research-autosave.js','research-browser.js','research-interactions.js']) vm.runInContext(fs.readFileSync(path.join(__dirname, 'static', file), 'utf8'), context, {filename:file});
  vm.runInContext(source, context, {filename:'app.js'});
  // These checks render only. Editing is exercised by the isolated v0.3 tests.
  vm.runInContext('captureResearchEdit=()=>null', context);
  await vm.runInContext('refresh()', context);
  let count = 0;
  for (const route of ['research','dashboard','products','suppliers','pricing','content','finance','settings']) {
    await vm.runInContext(`go('${route}')`, context);
    const html = element('#app').innerHTML;
    assert.ok(html.includes('<h1>'), `${route}: missing heading`);
    assert.ok(!html.includes('undefined'), `${route}: undefined value`);
    assert.ok(!html.includes('NaN'), `${route}: NaN value`);
    assert.ok(html.includes('本地原型'), `${route}: missing prototype label`);
    if (route === 'pricing') assert.ok(element('#price-results').innerHTML.includes('定价结果'));
    console.log(`PASS view render: ${route}`);
    count++;
  }
  for (const tab of ['market','supply','cases','tools','quality','connection']) {
    vm.runInContext(`route='research';researchTab='${tab}';render()`, context);
    const html = element('#app').innerHTML;
    assert.ok(html.includes('商品成交价上限'));
    assert.ok(!html.includes('NaN'));
    assert.ok(!html.includes('undefined'));
    if (tab === 'connection') assert.ok(html.includes('type="password"'));
    count++;
  }
  // Synthetic form-only fixtures stay inside the VM; no API write or real
  // candidate is created. Exercise both unknown and populated result panels.
  vm.runInContext(`researchData.cases=[{id:'synthetic-ui',revision:1,title:'<script>synthetic</script>',offerObservationId:'',skuObservationId:'',specification:'',mappingEvidence:'',mappingConfirmed:false,comparisons:[],quote:{},package:{},costs:{},checks:{},checksEvidence:{},marketEvidence:{},demandEvidence:{},rulesEvidence:{},cashEvidence:{},payment:'normal',orderFeeExempt:false,disposition:'open',assessment:{state:'needs_evidence',label:'资料不足',meaning:'Synthetic UI test only',needs:[],failures:[],warnings:[],calculation:null,recommended:null,comparison:{groups:{local:{count:0,median:null}},scope:'synthetic'},scenarios:[],cash:null}}];researchCaseId='synthetic-ui';researchTab='cases';route='research';render()`, context);
  assert.ok(element('#app').innerHTML.includes('利润：未计算'));
  assert.ok(element('#app').innerHTML.includes('&lt;script&gt;synthetic&lt;/script&gt;'));
  assert.ok(element('#app').innerHTML.includes('quote.unitPrice'));
  assert.ok(!element('#app').innerHTML.includes('undefined'));
  count++;
  vm.runInContext(`researchData.cases[0].assessment.calculation={profit:'10.00',margin:'20.00',totalCost:'40.00',lines:[{name:'采购成本',basis:'synthetic',cny:'40.00'}]};render()`, context);
  assert.ok(element('#app').innerHTML.includes('完全成本合计'));
  assert.ok(!element('#app').innerHTML.includes('undefined'));
  count++;
  vm.runInContext("productModal('product-1')", context);
  assert.ok(element('#modal').innerHTML.includes('供应商 SKU'));
  assert.ok(element('#modal').innerHTML.includes('type="button" class="button " data-action="close-modal"'));
  count++;
  vm.runInContext("supplierModal('supplier-1')", context);
  assert.ok(element('#modal').innerHTML.includes('支持单件代发'));
  count++;
  assert.equal(vm.runInContext("esc('<script>alert(1)</script>')", context), '&lt;script&gt;alert(1)&lt;/script&gt;');
  count++;
  vm.runInContext("data.products[0].name='<img src=x onerror=alert(1)>'; route='products'; render()", context);
  assert.ok(element('#app').innerHTML.includes('&lt;img src=x onerror=alert(1)&gt;'));
  assert.ok(!element('#app').innerHTML.includes('<img src=x onerror'));
  count++;
  console.log(`${count} view-function checks passed. No browser or external provider was used.`);
}
run().catch(error=>{console.error(error);process.exitCode=1;});
