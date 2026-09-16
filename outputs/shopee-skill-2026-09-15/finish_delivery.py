from pathlib import Path
import json,sys,datetime,io,contextlib,hashlib
from PIL import Image,ImageDraw,ImageFont
BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(BASE/'shopee-ph-selection/scripts'))
from build_daily import build

fontpath='C:/Windows/Fonts/msyh.ttc'
boldpath='C:/Windows/Fonts/msyhbd.ttc'
im=Image.new('RGB',(1500,2000),'#F6F8FA');dr=ImageDraw.Draw(im)
font=lambda n,b=False:ImageFont.truetype(boldpath if b else fontpath,n)
dr.text((65,38),'Shopee 菲律宾每日选品',font=font(45,True),fill='#14394A')
dr.text((67,101),'证据完整才进入测品审核 ｜ 单品测试总成本 ≤ 500 元',font=font(26),fill='#4E6474')
def box(x,y,w,h,title,subtitle,fill='#FFFFFF',outline='#AABFCC'):
    dr.rounded_rectangle((x,y,x+w,y+h),radius=18,fill=fill,outline=outline,width=2)
    dr.text((x+24,y+18),title,font=font(28,True),fill='#173E50')
    dr.text((x+24,y+63),subtitle,font=font(22),fill='#456173')
def arrow(x1,y1,x2,y2,color='#537D93'):
    dr.line((x1,y1,x2,y2),fill=color,width=5)
    if y2>y1:dr.polygon([(x2,y2),(x2-8,y2-13),(x2+8,y2-13)],fill=color)
    else:dr.polygon([(x2,y2),(x2-13,y2-8),(x2-13,y2+8)],fill=color)
stages=[
 ('01 刷新经营条件','费用、物流、现金、规则、报价有效期'),
 ('02 采集与去重','50–100条线索；颜色/尺寸不重复计SPU'),
 ('03 数据与合规检查','PH/PHP、30天SKU窗口、禁限售、权利'),
 ('04 需求与竞争','同规格≥10款/5店；销量、跨境与到手价'),
 ('05 1688逐SKU核验','报价、MOQ、代发、库存、备货、包重'),
 ('06 全成本与采购上限','基准≥20%且≥15元；组合压力不亏'),
 ('07 测试预算与全店资金','单品总成本≤500；现金、损失、履约合并'),
 ('08 Excel交店主人审','目标10–20不同SPU；不足时如实报告'),
 ('09 取得授权后分批测品','审核目标数不等于每日同时付费测试数'),
 ('10 复盘与对账','7/14/28天；完整队列；结果更新选品规则')]
for i,(title,sub) in enumerate(stages):
    y=180+i*166
    box(70,y,890,122,title,sub,fill='#E8F3F6' if i in [5,6,7] else '#FFFFFF')
    if i<9:arrow(515,y+122,515,y+163)
box(1020,470,420,170,'缺证 / 已过期','进入待补证队列',fill='#FFF0D7')
dr.text((1042,579),'保留原值与来源',font=font(22),fill='#7A551B')
arrow(960,530,1018,530)
box(1020,760,420,175,'明确失败','排除并记录原因',fill='#FDE9EA')
dr.text((1042,870),'不能靠评分抵消',font=font(22),fill='#8B3146')
arrow(960,862,1018,862)
box(1020,1130,420,260,'当前状态','22条历史候选',fill='#FFF0D7')
dr.text((1042,1238),'0条证据充分可测品',font=font(24,True),fill='#8B5412')
dr.text((1042,1290),'不能补数宣称成功',font=font(23),fill='#7A551B')
dr.text((68,1900),'人工60分钟：资金5 → 市场10 → 供应成本20 → 批审20 → 留档5',font=font(26,True),fill='#173E50')
dr.text((68,1950),'前提：Agent提前备齐证据；首次建库、报价等待、样品到货另计。',font=font(24),fill='#4E6474')
png=BASE/'选品流程图.png';im.save(png)
data=json.loads((BASE/'selection.json').read_text(encoding='utf-8'));data['flow_png']=png.name
(BASE/'selection.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
build(data,BASE/'菲律宾Shopee每日选品审核.xlsx')
# Preserve a small executed audit companion without installing a notebook runtime.
code='''from pathlib import Path
import json
base = Path.cwd()
data = json.loads((base / "selection.json").read_text(encoding="utf-8"))
m = data["observations"]; s = data["suppliers"]
result = {"market_rows": len(m), "distinct_products": len({r["product_id"] for r in m}),
          "epoch_sales_dates": sum(r.get("sales_calc_time") == "1970-01-01" for r in m),
          "supplier_rows": len(s), "zero_prices": sum(r.get("price") == 0 for r in s),
          "candidates": len(data["candidates"])}
print(json.dumps(result, ensure_ascii=False, indent=2))'''
import os
oldcwd=os.getcwd();os.chdir(BASE);buf=io.StringIO()
try:
    with contextlib.redirect_stdout(buf):exec(compile(code,'data-audit-cell','exec'),{})
finally:os.chdir(oldcwd)
nb={'nbformat':4,'nbformat_minor':5,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'}},'cells':[
 {'cell_type':'markdown','id':'summary','metadata':{},'source':['# 数据审计复现\n','仅核对已有原始观测数量和异常，不验证市场需求或盈利。\n','当前220市场观测、196商品ID、220异常销量日；600供应商观测，417零价；22候选。']},
 {'cell_type':'markdown','id':'method','metadata':{},'source':['## 输入与执行方法\n','在此目录运行；输入为selection.json及evidence源快照。\n','代码已在Python中顺序执行并保存原始输出；本机没有nbformat/Notebook内核，未声称通过Jupyter内核执行或界面检查。']},
 {'cell_type':'code','id':'audit','metadata':{},'source':code.splitlines(keepends=True),'execution_count':1,'outputs':[{'output_type':'stream','name':'stdout','text':buf.getvalue().splitlines(keepends=True)}]},
 {'cell_type':'markdown','id':'finding','metadata':{},'source':['## 解释\n','统计来自原始导入，仅说明覆盖与质量缺口。币种和窗口异常未解决前，有效准入数据为0；0价不是免费货源。来源校验见evidence/input-manifest.json。']} ]}
(BASE/'数据质量复现.ipynb').write_text(json.dumps(nb,ensure_ascii=False,indent=2),encoding='utf-8')
print('流程图、工作簿与已执行Python审计输出已保存')
