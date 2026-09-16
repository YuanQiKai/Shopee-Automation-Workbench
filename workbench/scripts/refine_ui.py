from pathlib import Path
import json
R=Path(__file__).resolve().parents[1]
p=R/'data/default-settings.json';d=json.loads(p.read_text(encoding='utf-8'));d['transaction_stress_pct']=None;p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
p=R/'frontend/app/page.tsx';s=p.read_text(encoding='utf-8')
s=s.replace('已接入物流资料和 38 条真实 SKU 记录','已接入物流资料和 {sups.reduce((n,s)=>n+s.skus.length,0)} 条真实 SKU 记录')
s=s.replace('38 个 SKU 来自 2 家真实 1688 商家。','{sups.reduce((n,s)=>n+s.skus.length,0)} 个 SKU 来自 {sups.length} 家真实 1688 商家。')
s=s.replace("['program_pct','项目/活动服务费 %'","['transaction_stress_pct','压力情景交易费率 %','按可能适用的较高费率；仅确认无更高费率时与基准相同'],['program_pct','项目/活动服务费 %'")
s=s.replace('新增可用现金 = 今日余额 − 已有未付款承诺 − 保护资金 − 其他已批准测试占用。','新增可用现金 = 80% ×（今日余额 − 已有未付款承诺 − 保护资金）− 其他已批准测试占用。')
s=s.replace("j.data.created_at.slice(0,19).replace('T',' ')","new Date(j.data.created_at).toLocaleString('zh-CN',{hour12:false})")
s=s.replace("{ev.reasons.map((r:string)=><li key={r}>{r}</li>)}","{ev.reasons.map((r:string)=><li key={r}>{reasonLabel(r)}</li>)}")
pos="const num=(x:any,prefix='')"
mapper="const reasonLabel=(x:string)=>({data_gate:'数据口径',demand_gate:'需求强度',competition_gate:'竞争可行性',available_cash_cny:'今日余额',commitments_cny:'已有未付承诺',realized_loss_cny:'本月确认损失',unresolved_loss_cny:'未决损失',activity_factor:'最低活动成交比例',commission_pct:'店铺佣金率',transaction_pct:'交易费率',transaction_stress_pct:'压力交易费率',transaction_base:'交易费收费基数',program_pct:'活动项目费率',fx_cny_per_php:'到账汇率',list_price_php:'标价',purchase_price_cny:'准确采购单价',purchase_units:'采购件数',cash_subsidy_php:'实际可收补贴',buyer_shipping_php:'买家运费',domestic_cny:'国内运费',packaging_cny:'额外包材费',purchase_tax_cny:'采购税票差额',customs_cny:'关税及清关附加',ads_cny:'广告分摊',affiliate_cny:'联盟佣金',returns_cny:'售后/COD损失准备',overhead_cny:'固定费用分摊',tax_cny:'经营税费分摊',other_cny:'其他费用',seller_topup_php:'卖家额外补运费',platform_other_php:'其他平台扣款',test_orders:'测试订单数',test_setup_cny:'样品等新增测试费用',test_spent_cny:'本款已累计测试支出'} as Obj)[x]||x.replace('data_gate','数据口径').replace('demand_gate','需求强度').replace('competition_gate','竞争可行性').replace('primary','主货源').replace('backup','备用货源');\n"
if 'const reasonLabel=' not in s:s=s.replace(pos,mapper+pos)
p.write_text(s,encoding='utf-8')
