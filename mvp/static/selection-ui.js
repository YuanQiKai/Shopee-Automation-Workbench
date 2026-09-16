'use strict';
function selectionRulesPage(){
  const p=researchData.selectionPolicy;if(!p)return empty('请重启本地服务','新规则尚未加载。');
  return `<section class="card"><div class="card-head"><h2>${esc(p.label)}</h2><span class="badge gray">${esc(p.version)}</span></div><div class="card-body"><p class="callout">${esc(p.basis)}</p><p><b>所有必选门槛通过 + 总分 ≥ ${p.thresholds.scoreMin} + 资金充足 → 可进入人工上架测试审核。</b><br>资料缺失 → 待补证；明确不通过 → 当前方案拒绝。允许测试不等于已经确定盈利。现有系统未接入店铺发布。</p></div></section>
  <div class="selection-rule-grid spaced">${p.dimensions.map(d=>`<section class="card"><div class="card-head"><h2>${esc(d.label)}</h2><span class="badge gray">${d.weight}分</span></div><div class="card-body"><p>${esc(d.rule)}</p></div></section>`).join('')}</div>
  <section class="card spaced"><div class="card-head"><h2>资金硬门槛</h2></div><div class="card-body"><p>${esc(p.cashRule)}</p><p>真实余额、已有承诺、退款/税款准备需先核实；计划订单与在途订单不能重复预留，跨产品须共同占用同一全店额度。</p></div></section>
  <section class="card spaced"><div class="card-head"><h2>上线后才有的数据，留到复盘验证</h2></div><div class="card-body"><p>第7天查曝光、可售与类目；第14天区分无点击与无转化，约100次有效访问零单只是复盘信号；第28天按实际净利、退款和交运决定优化或停售。零曝光零订单不直接判为无需求。</p><p>持续经营验证建议先积累至少20个已完成且对账订单、两次跨周履约批次，再检查平均全成本净利≥15元、净利率≥20%、无系统性质量/侵权/超时问题。样本仍小，不据此自动放量。本版实现的是上架前门槛，尚未接入订单数据。</p><p>规则保存在版本文件，后续调整必须说明依据并变更版本；旧候选自动重新核验。人工证据声明不是系统对凭证真伪的鉴定。</p></div></section>`;
}
function selectionEvidenceForm(c){
  const all=researchData.selectionFields||{},labels={competition:'竞争差异',profit:'推广成本',logistics:'计费重量与时限',supply:'供货实物与责任',compliance:'店主禁做清单',expansion:'复购与扩展（可选）',cash:'28天资金压力'};
  return `<details class="research-section" open><summary>6. 七维判定所需证据</summary><p class="image-note">新版条件对新旧候选同时生效。只有实际复核过才填写时间，不自动填“今天”。同规格销量请在第2节各竞品中录入。</p>
  <div class="fields">${input('报价/库存实际复核时间（含时区）','quote.observedAt',c.quote.observedAt||'','text','placeholder="YYYY-MM-DDTHH:mm:ss+08:00"')}</div>
  ${Object.entries(all).map(([key,fields])=>{const v=c.selectionEvidence?.[key]||{};return `<details class="research-section"><summary>${esc(labels[key]||key)}</summary><div class="fields">${fields.map(([f,label,type])=>type==='tri'?tri(label,'selectionEvidence.'+key+'.'+f,v[f]):input(label,'selectionEvidence.'+key+'.'+f,v[f]??'',type==='text'?'text':'number',type==='integer'?'min="0" step="1" data-type="integer"':type==='number'?'min="0" step="0.01"':'')).join('')}${input('实际复核时间（ISO，含时区）','selectionEvidence.'+key+'.observedAt',v.observedAt||'')}${proofFields('selectionEvidence.'+key,v,'核实依据（对应字段、凭证与测量方式）')}</div></details>`;}).join('')}</details>`;
}
function selectionComparisonFields(v,i){
  const prefix='comparisons.'+i;
  return `${input('该准确规格30天销量（件；禁止整链接混变体）',prefix+'.sales30d',v.sales30d??'','number','min="0" step="1"')}${input('销量30天窗口开始（含当日）',prefix+'.salesWindowStart',v.salesWindowStart||'','date')}${input('销量30天窗口结束（含当日）',prefix+'.salesWindowEnd',v.salesWindowEnd||'','date')}${select('已核实销量口径',prefix+'.salesScope',v.salesScope||'unknown',[['unknown','未知/待核实'],['same_spec_30d','同一准确规格的明确30天销量'],['cumulative','累计销量（不可用于判定）'],['mixed_variants','含其他变体（不可用于判定）']])}${input('此竞品实际复核时间（含时区）',prefix+'.observedAt',v.observedAt||'')}`;
}
function selectionAssessment(a){
  const s=a.selection;if(!s)return '<p class="image-note">七维结论等待保存与重新核验。</p>';
  return `<section class="selection-result"><h3>七维评分 ${s.score===null?'待证据完整':s.score+' / 100'}</h3><p class="image-note">${esc(s.version)} · ${a.canReviewListing?'可进入人工上架测试审核':'当前不可进入上架审核'}</p>${s.dimensions.map(d=>`<div class="selection-dimension"><div><b>${esc(d.label)}</b><span class="badge ${d.status==='pass'?'green':d.status==='fail'?'red':d.status==='unscored'?'gray':'orange'}">${({pass:'通过',fail:'不通过',unknown:'待补证',unscored:'未加分'})[d.status]} ${d.score===null?'—':d.score}/${d.weight}</span></div>${d.reasons.map(r=>`<p>${esc(r)}</p>`).join('')}</div>`).join('')}<details><summary>查看计算依据</summary>${Object.entries({validMarketSamples:'有效同规格样本',distinctShops:'独立店铺数',sampleSales30d:'样本30天销量',sampleTop3ShopSharePct:'样本前三店占比 %',crossBorderMedianPHP:'跨境到手价中位数 PHP',dispatchSlackHours:'交运余量 小时',logisticsSharePct:'物流成本比例 %',cash28DaysCNY:'28天保守占资 CNY',cashUsable80PctCNY:'可用资金80% CNY'}).map(([k,l])=>`<p>${l}：${esc(s.metrics[k]??'待核实')}</p>`).join('')}${s.stress?`<p>全部物流组合压力净利：${money(s.stress.profit)}</p>`:''}</details></section>`;
}
