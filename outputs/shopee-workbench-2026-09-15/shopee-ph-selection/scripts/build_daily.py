"""Create a review workbook from evidence-backed normalized input, never live scrape."""
import argparse,json,datetime
from pathlib import Path
import xlsxwriter
from xlsxwriter.utility import xl_col_to_name
from selection_math import calculate,evaluate,REQUIRED_COSTS,LOGISTICS,D

def build(data, output):
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    w=xlsxwriter.Workbook(str(output),{'strings_to_formulas':False,'strings_to_urls':False})
    w.set_properties({'title':'Shopee菲律宾每日选品审核','author':'店铺选品工作区','comments':'真实证据与未知值分开；审核草案；不代表已盈利。'})
    style={'font_name':'Microsoft YaHei','font_size':10,'valign':'top','text_wrap':True}
    fmt={
      'text':w.add_format({**style,'bottom':1,'bottom_color':'#DCE4EA'}),
      'title':w.add_format({**style,'font_size':20,'bold':True,'font_color':'#FFFFFF','bg_color':'#12354A'}),
      'note':w.add_format({**style,'font_color':'#47586A','bg_color':'#F0F5F8'}),
      'header':w.add_format({**style,'bold':True,'font_color':'white','bg_color':'#24566D'}),
      'input':w.add_format({**style,'font_color':'#195ABD','bg_color':'#EAF2FF','num_format':'0.00########'}),
      'num':w.add_format({**style,'num_format':'#,##0.00;[Red]-#,##0.00','bg_color':'#F1F5F6'}),
      'pct':w.add_format({**style,'num_format':'0.0%','bg_color':'#F1F5F6'}),
      'warn':w.add_format({**style,'font_color':'#87540E','bg_color':'#FFF1D5'}),
      'red':w.add_format({**style,'font_color':'#AD2339','bg_color':'#FFE9EE'}),
      'good':w.add_format({**style,'font_color':'#176047','bg_color':'#E2F3E9'}),
      'link':w.add_format({**style,'font_color':'#1763B5','underline':1}),
      'date':w.add_format({**style,'num_format':'yyyy-mm-dd hh:mm','font_color':'#195ABD','bg_color':'#EAF2FF'})}
    def sheet(name,headers,note,widths=None):
        s=w.add_worksheet(name);s.hide_gridlines(2);s.freeze_panes(4,2);s.set_zoom(85)
        s.merge_range(0,0,0,max(len(headers)-1,3),name.replace('_',' · ',1),fmt['title']);s.set_row(0,38)
        s.merge_range(1,0,2,max(len(headers)-1,3),note,fmt['note']);s.set_row(1,26);s.set_row(2,22)
        s.write_row(3,0,headers,fmt['header']);s.set_row(3,34)
        for i in range(len(headers)):s.set_column(i,i,(widths or {}).get(i,22))
        s.set_landscape();s.set_paper(9);s.fit_to_pages(1,0);s.repeat_rows(0,3)
        s.set_footer('&L菲律宾选品 · 证据审核&R&P / &N')
        return s
    def putrows(s,rows,height=72):
        for i,row in enumerate(rows,4):
            for j,v in enumerate(row):
                if v is None:s.write_blank(i,j,None,fmt['warn'])
                elif isinstance(v,str) and v.startswith(('https://','http://')):s.write_url(i,j,v,fmt['link'],v)
                else:s.write(i,j,v,fmt['text'])
            s.set_row(i,height)
        if rows:s.autofilter(3,0,3+len(rows),len(rows[0])-1)
    def ff(s,row,col,formula,cache='',typ='num'):
        if cache is None:cache=''
        if not isinstance(cache,(str,int,float)):cache=float(cache)
        s.write_formula(row,col,formula,fmt[typ],cache)
    cands=data['candidates'];results={c['id']:evaluate(c,data['as_of']) for c in cands}
    def localdate(value):
        return datetime.datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(datetime.timezone(datetime.timedelta(hours=8))).replace(tzinfo=None)
    now=localdate(data['as_of'])
    s=sheet('00_审核入口',['项目','本轮结果','含义及限制','建议行动'],
      '先读这一页，再看01逐品结论。蓝色为可录入区；空白=未知。冻结结论必须由更新后的证据重新生成，改单元格不等于重新批准。',{0:26,1:24,2:75,3:58})
    good=sum(r['decision']=='可进入人工测品审核' for r in results.values())
    rows=[['运行时间',data['as_of'],'以来源自身观测日期判断新鲜度','不可用运行时间替换历史数据日期'],
      ['历史候选记录',len(cands),'尚待准确规格/SPU复核；不能全部视为独立已验证商品','见01与02'],
      ['证据充分可测品',good,'当前所有正式成本缺失；真实成功盈利数也为0','不采购、不投放、不上架'],
      ['原始市场记录',len(data.get('observations',[])),'原始采集并非本轮新增，币种与窗口异常','见07与08'],
      ['1688历史货源记录',len(data.get('suppliers',[])),'起价及整条offer，不是当前同SKU报价','见06；0价不能当免费'],
      ['利润门槛','20% 且 15元','完全成本预计利润/商品收入；条件，不是保证','基准、采购上限、压力三项一起审'],
      ['单品测试总成本','≤500 CNY','含采购、物流、平台费、推广、样品、售后等','不能仅限制采购额'],
      ['一分钟审一款的前提','标准化证据已完整','目标每日人工60分钟；首次建库与等待报价另计','先做3天计时试跑'],
      ['验收缺口','未达到≥10个成功选品','市场有效窗口、同SKU报价、运费费用及现金资料不全','补齐数据后重跑；不以历史候选充数']]
    putrows(s,rows,58)
    s.write_datetime('F2',now,fmt['date']);s.set_column('F:F',24)

    s=sheet('01_逐品结论',['ID','产品方向','本轮结论','事实证据','判断说明（推断）','拟验证差异','缺口与风险','补证顺序','市场链接','1688线索','预计利润CNY','利润率','测试成本CNY'],
      '逐款列明冻结的证据与结论；方向性推断不是需求、质量、同款、利润或授权事实。真实经营成功只能由成熟实单对账证明。',{1:30,2:24,3:65,4:58,5:46,6:65,7:50,8:42,9:42})
    putrows(s,[[c['id'],c['name'],results[c['id']]['decision'],c['fact'],c['inference'],c.get('difference'),c['gaps'],c['recommendation'],c.get('market_url'),c.get('supply_url'),results[c['id']].get('profit_cny'),results[c['id']].get('margin'),results[c['id']].get('test_total_cny')] for c in cands],135)
    for i,c in enumerate(cands,4):
        s.write(i,2,results[c['id']]['decision'],fmt['warn'])
        if results[c['id']].get('margin') is not None:s.write_number(i,11,float(results[c['id']]['margin']),fmt['pct'])
    s=sheet('02_逐项证据门槛',['ID','产品','维度','实际值/已知状态','判定门槛','符合程度','解释及影响','证据定位'],
      '达到数字门槛与证据有效是两件事。未核实、不适用和不通过分别记录；不生成虚假的总体通过率。',{1:28,2:22,3:62,4:67,5:21,6:62,7:65})
    er=[]
    for c in cands:
        er.extend([[c['id'],c['name']]+r for r in c['evidence_rows']])
    putrows(s,er,90)

    costs=sheet('03_逐品成本',['ID','产品','券后商品PHP','额外补贴PHP','CNY每PHP','SKU采购价CNY','采购数量/套','采购联动附加率','样品拍摄等固定测试费','测试计划单量','SKU报价证据','报价截止','费用口径审核','费用完整','其他成本CNY','压力其他成本','商品收入CNY','采购成本CNY','单件完全成本','预计利润CNY','预计利润率','采购上限CNY','组合压力利润','测试总成本','500元最多测试单量','成本判定'],
      '一个销售单元=确定SKU一单（可以是套装）。成本预测不是已实现利润；仅填写准确报价和04全部费用，缺项不计算。报价观测≤24h另由Skill检查。修改后需重新生成审核结论。',{1:28,10:48,11:23,12:20})
    fees=sheet('04_费用明细',['ID','产品','费项键','费项名称','币种','基准金额','压力金额覆盖','状态','规则/基数/舍入/封顶/分摊','依据','有效期截止','基准CNY','压力CNY','本行完整'],
      '每款18项逐项核实；0要有免费或不适用依据。交易费压力金额必须填；国内运费/仓包/SLS在压力情景再×1.15，PHP费用用汇率×0.95。广告和售后可用有依据的预算，公共费率参考不自动填成本。',{1:28,3:37,8:65,9:60,10:24})
    for i,c in enumerate(cands,4):
        r=i+1;m=c.get('model') or {};res=results[c['id']]
        costs.write_row(i,0,[c['id'],c['name']],fmt['text']);costs.set_row(i,60)
        fieldcols={'net_sale_php':2,'extra_subsidy_php':3,'fx':4,'quote_cny':5,'purchase_units':6,'purchase_surcharge_rate':7,'setup_cny':8,'test_orders':9,'quote_evidence':10}
        for field,col in fieldcols.items():costs.write(i,col,m.get(field),fmt['input'])
        if m.get('quote_valid_until'):costs.write_datetime(i,11,localdate(m['quote_valid_until']),fmt['date'])
        else:costs.write_blank(i,11,None,fmt['date'])
        costs.write(i,12,'已核实' if m.get('costs_reviewed') else '待核实',fmt['input'])
        costs.data_validation(i,12,i,12,{'validate':'list','source':['已核实','待核实']})
        costs.data_validation(i,2,i,9,{'validate':'decimal','criteria':'>=','value':0,'error_type':'stop'})
        first=5+(i-4)*len(REQUIRED_COSTS);last=first+len(REQUIRED_COSTS)-1
        ls={x['key']:x for x in m.get('fee_lines',[])}
        fres={x['key']:x for x in res.get('fee_results',[])}
        for j,(key,label) in enumerate(REQUIRED_COSTS.items()):
            fr=first+j;fi=fr-1;line=ls.get(key,{})
            vals=[c['id'],c['name'],key,label,line.get('currency'),line.get('amount'),line.get('stress_amount'),line.get('status','待核实'),line.get('calculation'),line.get('evidence')]
            fees.write_row(fi,0,vals,fmt['input']);fees.set_row(fi,58)
            if line.get('valid_until'):fees.write_datetime(fi,10,localdate(line['valid_until']),fmt['date'])
            fees.data_validation(fi,4,fi,4,{'validate':'list','source':['CNY','PHP']})
            statuses=['已核实','不适用']+(['预算'] if key in {'ads','affiliate','returns','overhead','other'} else [])
            fees.data_validation(fi,7,fi,7,{'validate':'list','source':statuses})
            extra=f',ISNUMBER(G{fr}),G{fr}>=0' if key=='transaction' else ''
            state='OR('+','.join(f'H{fr}="{a}"' for a in statuses)+')'
            ff(fees,fi,13,f'=IF(AND(ISNUMBER(F{fr}),F{fr}>=0,OR(E{fr}="PHP",E{fr}="CNY"),{state},I{fr}<>"",J{fr}<>"",ISNUMBER(K{fr}),K{fr}>=\'00_审核入口\'!$F$2,OR(H{fr}<>"不适用",F{fr}=0),OR(G{fr}="",AND(ISNUMBER(G{fr}),G{fr}>=0)){extra}),"完整","待补证")','完整' if line else '待补证','warn')
            fx=f"'03_逐品成本'!E{r}"
            ff(fees,fi,11,f'=IF(AND(N{fr}="完整",ISNUMBER({fx}),{fx}>0),ROUND(ROUND(F{fr}*IF(E{fr}="PHP",{fx},1),10),2),"")',fres.get(key,{}).get('base_cny'))
            mul='1.15' if key in LOGISTICS else '1'
            ff(fees,fi,12,f'=IF(AND(N{fr}="完整",ISNUMBER({fx}),{fx}>0),ROUND(ROUND(IF(ISNUMBER(G{fr}),G{fr},F{fr})*{mul}*IF(E{fr}="PHP",{fx}*0.95,1),10),2),"")',fres.get(key,{}).get('stress_cny'))
        ff(costs,i,13,f'=IF(COUNTIF(\'04_费用明细\'!N{first}:N{last},"完整")=18,"完整","待补证")','完整' if not res['gaps'] else '待补证','warn')
        ff(costs,i,14,f'=IF(N{r}="完整",SUM(\'04_费用明细\'!L{first}:L{last}),"")',res.get('other_cny'))
        ff(costs,i,15,f'=IF(N{r}="完整",SUM(\'04_费用明细\'!M{first}:M{last}),"")',res.get('stress_other_cny'))
        ready=f'AND(COUNT(C{r}:J{r})=8,C{r}>0,D{r}>=0,E{r}>0,F{r}>=0,G{r}>0,G{r}=INT(G{r}),H{r}>=0,I{r}>=0,J{r}>0,J{r}=INT(J{r}),K{r}<>"",ISNUMBER(L{r}),L{r}>=\'00_审核入口\'!$F$2,M{r}="已核实",N{r}="完整")'
        exprs={16:(f'ROUND(ROUND((C{r}+D{r})*E{r},10),2)','revenue_cny'),17:(f'ROUND(ROUND(F{r}*G{r}*(1+H{r}),10),2)','procurement_cny'),18:(f'R{r}+O{r}','total_cost_cny'),19:(f'Q{r}-S{r}','profit_cny'),20:(f'IF(Q{r}>0,T{r}/Q{r},"")','margin'),22:(f'ROUND(ROUND((C{r}+D{r})*E{r}*0.95,10),2)-ROUND(ROUND(F{r}*1.1*G{r}*(1+H{r}),10),2)-P{r}','stress_profit_cny'),23:(f'ROUND(I{r}+J{r}*S{r},2)','test_total_cny'),24:(f'IF(S{r}>0,MAX(0,INT((500-I{r})/S{r})),"")','max_test_orders')}
        for col,(exp,key) in exprs.items():ff(costs,i,col,f'=IF({ready},{exp},"")',res.get(key),typ='pct' if col==20 else 'num')
        budget=f'Q{r}-O{r}-ROUNDUP(MAX(15,0.2*Q{r}),2)'
        cache_ceiling=res.get('quote_ceiling_cny') if res.get('quote_ceiling_cny') is not None else res.get('ceiling_note','')
        ff(costs,i,21,f'=IF({ready},IF({budget}<0,"无非负可行采购价",ROUNDDOWN(({budget}+0.005-0.0000000001)/(G{r}*(1+H{r})),2)),"")',cache_ceiling)
        ff(costs,i,25,f'=IF({ready},IF(AND(T{r}>=15,U{r}>=0.2,W{r}>=0,X{r}<=500),"成本条件通过","成本条件不通过"),"待补证")',res['status'],'warn')
    costs.autofilter(3,0,3+len(cands),25);fees.autofilter(3,0,3+len(cands)*18,13)

    s=sheet('05_500元与现金',['检查项','计算/控制规则','本轮值或状态','依据','审核重点'],
      '同一预算不可逐品重复使用；历史启动资金不是当前余额。测试成本、最坏损失和峰值垫资分别计算。',{0:28,1:90,2:28,3:55,4:60})
    putrows(s,data.get('cash_rows',[]),80)
    s=sheet('06_1688历史货源',['采集时间','查询词','1688商品ID','商品标题','供应商','原始起价CNY','MOQ原值','代发原值','库存原值','零价/有效性','详情链接','证据定位'],
      '原始历史来源记录；未经本轮SKU/税/阶梯/库存复核。不表示已匹配同款或可按起价买整套。0价标为无效，原值保留。',{1:25,3:60,4:35,10:50,11:65})
    putrows(s,[[x.get('observed_at'),x.get('query'),x.get('product_id'),x.get('title'),x.get('store_name'),x.get('price'),x.get('min_order_quantity'),str(x.get('is_drop_shipping')),x.get('stock_count'),'0价/缺失无效' if not x.get('price') else '历史起价待复核',x.get('url'),x.get('source')] for x in data.get('suppliers',[])],65)
    s=sheet('07_历史市场原值',['记录ID','采集时间','关键词','商品ID','店铺ID','原始标题','原始价格','币种状态','原始销量字段','销量计算日','评分原值','评论数原值','本轮可用于放行','证据定位'],
      '原始价格和销量故意不进入正式利润/市场规模。sales_calc_time=1970及PH/THB冲突无法证明真实近期需求。',{5:68,7:43,13:68})
    putrows(s,[[x.get('id'),x.get('date'),x.get('keyword'),x.get('product_id'),x.get('shop_id'),x.get('title'),x.get('price'),x.get('currency'),x.get('sales_count'),x.get('sales_calc_time'),x.get('ratings'),x.get('ratings_count'),'否，待币种/窗口/SKU核实',x.get('source')] for x in data.get('observations',[])],68)
    s=sheet('08_数据问题',['问题ID','类型','字段','原始值','影响','来源','修复动作','状态'],
      '历史问题逐条保留；重复记录是跨查询重复观测，不能误说重复订单。来源不一致要解决，不静默改币种或日期。',{3:45,4:62,5:65,6:65})
    putrows(s,[[x.get('id'),x.get('type'),x.get('field'),x.get('value'),x.get('impact'),x.get('source'),x.get('action'),x.get('status')] for x in data.get('issues',[])],85)
    s=sheet('09_市场与官方证据',['来源ID','主题','本轮读取结果','结论性质','适用限制','来源链接/文件','读取日期'],
      '官方宏观数据说明市场背景，不证明任何单品可以盈利。所有比例口径保留；第三方搜索结果不作为正式当前报价。',{1:34,2:78,3:22,4:76,5:68})
    putrows(s,data.get('sources',[]),100)
    s=sheet('10_SOP与阈值',['步骤','时间目标/频率','输入','处理和产出','放行条件','失败处理'],
      '产能目标需先有有效候选储备。首次资料建档、供应商等待与样品到货不能压缩成一小时；三天试运行后再承诺产能。',{0:25,2:55,3:80,4:70,5:60})
    putrows(s,data.get('sop_rows',[]),92)
    s=sheet('11_复盘与待补资料',['类型','需要的数据','用途/最小范围','本轮状态','责任/下一步'],
      '店主审核后仍需另行授权外部操作；本轮没有产生采购、广告或上架。',{0:28,1:75,2:80,3:28,4:58})
    putrows(s,data.get('next_rows',[]),90)
    flow=Path(data.get('flow_png','__no_flow__'))
    if not flow.is_absolute():flow=output.parent/flow
    if data.get('flow_png') and flow.exists():
        s=sheet('12_流程图',['每日选品流程','判定','输出','备注'],'完整路径：证据→市场→供应→利润→500元测试→全店现金→人审。',{0:40,1:40,2:40,3:40})
        s.insert_image('A5',str(flow),{'x_scale':0.60,'y_scale':0.60})
    w.close()
    return results

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    data=json.loads(Path(a.input).read_text(encoding='utf-8-sig'))
    result=build(data,a.output)
    Path(a.output).with_suffix('.results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(f'已生成 {len(result)} 条审核记录；可进入测品审核 {sum(x["decision"]=="可进入人工测品审核" for x in result.values())} 条')
