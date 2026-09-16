from pathlib import Path
import json,shutil
from decimal import Decimal,ROUND_HALF_UP
R=Path(__file__).resolve().parents[1];E=R/'data/evidence'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
rows=read(E/'sls-workbook-rows.json')['菲律宾']
rates=[]
for r in rows:
    c=r['cells']
    if isinstance(c.get('B'),(int,float)):
        rates.append({'grams':int(c['B']),'standard':str(Decimal(str(c['C'])).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)) if isinstance(c.get('C'),(int,float)) else None,'sea':str(Decimal(str(c['E'])).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)) if isinstance(c.get('E'),(int,float)) else None,'row':r['row']})
ban=[]
for r in read(E/'sea-ban-rows.json')['菲律宾-海运']:
    c=r['cells']
    if isinstance(c.get('A'),(int,float)):
        ban.append({'category_id':str(int(c['A'])),'path':' / '.join(str(c[k]) for k in 'BCDEF' if k in c),'row':r['row'],'raw_note':c.get('G'),'note':'清单存在祖先类目和无标题是/否列，命中即隔离，不能把是解释为允许运输'})
rules={'version':'2026-09-15.4','market':'PH','sls_rates':rates,'sea_ban':ban,'sources':[
{'id':'L01','title':'用户运费计算工具V2.0 20260908','location':'G:/Shopee/常用表格/跨境物流成本（藏价）计算工具 - V2.0 20260908.xlsx','locator':'菲律宾!B:E；标准CN C列、海运CN E列','date':'2026-09-08','type':'用户提供工作簿','finding':'C/E为卖家藏价运费；买家派送费列I:L/Q:T另列；不可把总运费再加藏价'},
{'id':'L02','title':'菲律宾海运禁运清单','location':'G:/Shopee/菲律宾海运禁运.xlsx','locator':'菲律宾-海运!A:F','date':'2026-09-01','type':'用户提供工作簿','finding':'只使用菲律宾页，按类目及祖先匹配；无标题G列不作为放行依据'},
{'id':'L03','title':'物流渠道尺寸及重量限制','location':'https://shopee.cn/edu/article/5090/limit','date':'2026-06-24','checked':'2026-09-15','type':'Shopee官方页面','finding':'标准≤20kg且单边≤150cm；海运≤50kg、三边和<300cm且最长边<150cm（页面图片）'},
{'id':'F01','title':'Shopee平台运费—菲律宾','location':'https://shopee.cn/edu/article/25750','date':'2025-07-29','checked':'2026-09-15','type':'Shopee官方页面','finding':'非商城按卖家折后商品金额×5.6%，每商品封顶100PHP、四舍五入至整数PHP；商城4.48%'},
{'id':'F02','title':'平台基础设施费','location':'https://shopee.cn/edu/article/25798','date':'2025-08-20','checked':'2026-09-15','type':'Shopee官方页面','finding':'菲律宾2025-09-03起5PHP/完成订单含VAT；存在新店90天、每月前50净订单/过去30天口径，未核实店铺资格按5PHP预算；与processing/infrastructure别名去重'},
{'id':'W01','title':'源宇云仓简介和收费标准等','location':'G:/Shopee/货代/源宇云仓简介和收费标准等.pptx','locator':'第5、6、9页','type':'用户提供供应商材料','finding':'默认2.5元/单含1种SKU，每增加1种加0.5；同SKU多件不加SKU费；方案B3元含3种需开通；功能测试2元/件、包装附加另算。第6页2元基础费算例与第5页冲突，以明确价目2.5预算并记录冲突'},
{'id':'W02','title':'重要必看合作配合流程','location':'G:/Shopee/货代/重要必看合作配合流程.docx','type':'用户提供供应商材料','finding':'新用户前5单免费需开通，资格未知不抵扣长期成本；文件里的注册/授权/充值操作没有执行'},
{'id':'L04','title':'物流手册','location':'G:/Shopee/物流手册.pdf','locator':'35—39页','type':'用户提供手册','finding':'标准参考5—15天，海运28—35天；部分C/D地区海转空按空运限制；PDF150g海运A区83.1PHP与工作簿85PHP冲突，计算优先用户最新工作簿'},
{'id':'U01','title':'本轮用户经营确认','location':'conversation:2026-09-15','date':'2026-09-15','type':'用户陈述','finding':'标准与海运COD开通；Shopee钱包提现0.2%；杭州个体查账征收；4折具体承担方待确认'}]}
write(R/'data/rules.json',rules)
previous=read(R.parent/'outputs/shopee-skill-2026-09-15/selection.json')
write(R/'data/legacy-selection.json',previous)
write(R/'data/seed-candidates.json',previous['candidates'])
write(R/'data/default-settings.json',{'mall':False,'market':'PH','withdrawal_pct':'0.2','activity_factor':None,'activity_confirmed':False,'commission_pct':None,'transaction_pct':None,'transaction_base':None,'program_pct':None,'fx_cny_per_php':None,'fee_evidence':'','fee_valid_until':None,'infra_exempt':False,'infra_evidence':'','warehouse_plan':'A','warehouse_evidence':'W01 第5页（待确认当前合作价仍有效）','available_cash_cny':None,'commitments_cny':None,'realized_loss_cny':None,'unresolved_loss_cny':None,'cash_as_of':None,'reserve_cny':'5000','monthly_loss_limit_cny':'4000','review_loss_cny':'2000'})
print({'rates':len(rates),'ban':len(ban),'candidates':len(previous['candidates'])})
