from pathlib import Path
import json,hashlib,shutil,datetime,sys,io,contextlib
BASE=Path(__file__).resolve().parent
ROOT=BASE.parent.parent
SKILL=BASE/'shopee-ph-selection'
E=BASE/'evidence';E.mkdir(exist_ok=True)
ASOF=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec='seconds')
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
manifest=[];all_candidates=[];market=[];suppliers=[]
for day,folder,section in [('2026-09-10','shopee-plan-2026-09-10','market'),('2026-09-11','shopee-daily-2026-09-11','queries')]:
    for filename in ['raw-observations.json','candidates.json']:
        p=ROOT/'outputs'/folder/filename;dest=E/f'{day}-{filename}';shutil.copy2(p,dest)
        manifest.append({'source':str(p.relative_to(ROOT)),'snapshot':str(dest.relative_to(BASE)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    raw=read(ROOT/'outputs'/folder/'raw-observations.json')
    cc=read(ROOT/'outputs'/folder/'candidates.json')
    for idx,c in enumerate(cc):all_candidates.append({**c,'record_source':f'evidence/{day}-candidates.json#/{idx}'})
    for sec in [section]+(['suppliers'] if day=='2026-09-10' else []):
        for qi,q in enumerate(raw.get(sec,[])):
            for ti,block in enumerate(q.get('result',{}).get('content',[])):
                if block.get('type')!='text':continue
                try:body=json.loads(block['text'])
                except (ValueError,TypeError):continue
                rows=body.get('data')
                if not isinstance(rows,list):continue
                for ri,r in enumerate(rows):
                    if not isinstance(r,dict):continue
                    source=f'evidence/{day}-raw-observations.json#/{sec}/{qi}/result/content/{ti}/text→JSON/data/{ri}'
                    query=q.get('keyword',q.get('args',{}).get('name',q.get('args',{}).get('search_name','')))
                    observed=raw.get('observedAt',q.get('finished',day))
                    if 'sales_count' in r:
                        market.append(dict(r,id=f'M-{len(market)+1:04d}',keyword=query,date=observed,source=source,currency='未确认：PH查询，接口字典价格标THB',valid=False))
                    elif 'store_name' in r:
                        suppliers.append(dict(r,observed_at=observed,query=query,source=source))
old=read(ROOT/'outputs/selection-sop-review-2026-09-14/dist/review-data.json')
issues=old['issues']
issues += [dict(id='NEW-001',type='本轮接口事实',field='Sorftime查询',value='MCP使用次数已达到上限，请升级您的套餐',impact='无法取得新市场与货源数据；并不表示需求为0',source='本轮工具调用；source-log.json',action='恢复已有服务权限/额度，或取得合法来源导出；未购买套餐',status='未解决'),dict(id='NEW-002',type='本轮访问限制',field='1688详情读取',value='网页读取失败；浏览器站点安全策略阻止',impact='无法取得当前SKU、阶梯价和现货证据',source='source-log.json',action='提供用户合法取得的SKU报价与包装物流证据；不绕过限制',status='未解决')]
save(E/'input-manifest.json',manifest)
by_offer={str(r['product_id']):r for r in suppliers}
angles=[
 ('A 优先补证','洗衣防缠绕是明确可描述的使用场景，套装有机会分摊每单固定费；要用同规格成交与实物测试证实。','比较网眼、拉链包边、尺寸和套装件数，不借竞品品牌。'),
 ('A 优先补证','衣物分装可与洗漱/鞋袋服务同类旅行客户；体积重和单件代发可能否定经济性。','现有7.8元为历史起价且代发原字段为false，不能认定支持当前模式。'),
 ('A 优先补证','空洗漱包无需搭售化妆品，可突出悬挂和分仓；这是结构优势假设。','主货源空缺，需核实挂钩强度、空包包装重；不含液体、不直接称防水。'),
 ('B 暂缓单卖','结构简单但低价方向容易被固定处理费和国际运费吃掉利润；可研究多件组合。','多件组合会改变SKU和竞品可比性，不能拿单只销量配整套定价。'),
 ('B 先看体积','能服务衣柜整理场景；悬挂袋的大包装体积可能使跨境物流不合算。','先取得折叠包装尺寸，再核承重和缝线；图片视觉轻薄不等于计费轻。'),
 ('B 低优先','有发饰整理用途，但低价竞争和挂装问题可能抬高售后成本。','只研究成人收纳用途和无侵权图案；不能推断儿童用品准入。'),
 ('C 属性待核','桌面理线需求线索存在，但自粘属性、Choice样本及品牌字段冲突降低可比性。','背胶/成分和承运未知；先明确是否符合不做化学相关产品的边界。'),
 ('C 属性待核','被动绕线工具可整理电器外部线材；背胶失效和靠近热源使用可能增加投诉。','先证实无带电组件、胶黏属性、适配表面；不做电气安全承诺。'),
 ('B 规格优先','被动整理套管可按长度/直径区分用途；规格错配与安装难度可能拉低转化。','核实每米/每卷单位，排除电气绝缘或阻燃认证诉求。'),
 ('C 属性待核','替换芯可能形成后续需求，但本轮没有真实复购数据，不能计复购率。','粘胶相关属性和剩余纸张数、撕取效果未核；先确认经营边界。'),
 ('B 低优先','浴室排水口过滤是可验证的场景；低客单、孔径不匹配和排水慢可能否定方案。','只研究浴室非食品接触用途；不可声称抗菌或除臭。'),
 ('B 暂缓单卖','上装下抽可演示使用价值，但低价方向需验证组合后仍有市场需求。','需主货源、袋口和挂带样品检查；无证据不推导高转化。'),
 ('A 优先补证','不带胶的可重复绑带符合被动理线方向，套装有机会覆盖固定费。','0.03元为历史起价，不是50条整套报价；自粘一词需确认是钩毛还是背胶。'),
 ('A 优先补证','网眼空包易做尺寸和可见性演示，可与旅行整理共享目标客群。','1.13元历史起价且代发字段false；单件供货、尺寸、包重重新核实。'),
 ('B 重量先筛','折叠裤架有空间利用卖点，但金属杆、体积和关节质量可能不适合轻小跨境。','历史8.5元不是当前SKU报价；包装超过500g即不符合当前门槛。'),
 ('A 优先补证','双层空包可以表达线材分仓；不含任何带电配件时可研究相邻旅行需求。','主货源缺失；图中的充电器等不能默认属于套装，不复制防水宣称。'),
 ('B 客单待核','首饰分格有收纳用途，但硬盒体积和内衬质量可能增加成本与售后。','不含首饰，确认盒体尺寸、分隔固定、划伤测试及外观权利。'),
 ('B 适配先筛','挂门结构可避免胶粘，但门厚/门缝差异增加不适配风险。','先测门厚范围、承重、防刮和包装重；不是宣称适配全部家庭。'),
 ('B 质量先筛','小件晾晒用途明确；夹力、弹簧锈蚀和毛刺需要样品证据。','每个10夹的准确件数、材质、包重与备用货源都缺。'),
 ('B 规格先筛','空文件整理袋可拓展桌面收纳客群；跨不同用途的销量不能合并。','A4适配须实际测量，文件袋不能用内衣收纳款销量替代。'),
 ('C 暂缓','孔盖属于被动整理配件，但购买依赖开孔尺寸，错配可能导致高退货。','先验证常见尺寸的真实需求，排除受保护品牌/设计。'),
 ('C 暂缓','编织套管可以研究被动收束用途，但长度和直径单位容易错配。','20米竞品标题不能对应1米采购起价，绝缘/阻燃/防咬宣称须排除。')]
normalized=[]
for i,c in enumerate(all_candidates):
    cid=f'C{i+1:02d}';raws=[x for x in market if str(x.get('product_id'))==str(c.get('market_id'))]
    keyword=c.get('keyword') or (raws[0]['keyword'] if raws else '需重建同规格查询')
    group=[x for x in market if x['keyword']==keyword]
    url=c.get('source_supply');offer=str(url).split('/offer/')[-1].split('.')[0] if url else None
    su=by_offer.get(offer);start=su.get('price') if su else c.get('supply_price_from')
    raw_sales=c.get('monthly_raw',c.get('sales_raw'));raw_price=c.get('price_raw')
    supplyfact=(f'1688历史起价{start}元；MOQ={su.get("min_order_quantity") if su else c.get("supply_moq_raw")}；代发原字段={su.get("is_drop_shipping") if su else c.get("supply_drop_raw")}；未同SKU核验' if url else '未取得该方向可配对的1688货源证据')
    fact=f'历史{c.get("observed_at","")[:10]}记录：价格原值{raw_price}（币种未确认）；销量字段{raw_sales}（窗口未核实）；{supplyfact}。'
    pr,infer,extra=angles[i]
    focus=c.get('check') or c.get('verification_focus') or ''
    missing='PH/PHP与30天SKU销量；准确SKU规格及货源报价；包装计费重与运费；本店完整费项、活动、税与汇率；当前现金/未决损失；样品/合规/图权。'+extra
    ev=[
      ['数据质量',f'原销量日={c.get("sales_calc_time")}; PH查询/THB字典冲突','PH/PHP与明确30天SKU口径有效','待补证','不能用于定价、月销量、市场规模或利润事实',c['record_source']],
      ['需求',f'相关关键词原始样本{len(group)}条；有效可比样本0；单条原始销量字段{raw_sales}','≥10可比商品/5店；30天合计≥300件；3店各≥30件','待补证','原始样本未证同规格和有效窗口，无法比较达标程度',raws[0]['source'] if raws else c['record_source']],
      ['竞争与价格',f'价格原值{raw_price}，币种未确认；本地/跨境可比组未完成','CR3≤70%；2跨境店各≥30件；到手价≤跨境中位数110%','待补证','未计算价格分布或集中度，不能把单个畅销链接当入场证据',c['record_source']],
      ['趋势与质量','暂无可用3期趋势；样品未验','同规格3期观察；样品确认差异点与重要质量项','待补证',focus,c['record_source']],
      ['1688货源',supplyfact,'24h内逐SKU报价；可单件代发；MOQ兼容；库存≥10套；备货≤48h','仅线索' if url else '缺货源',extra,(su['source'] if su else c['record_source'])],
      ['物流履约','包装尺寸/实重/体积重、净运费和各段时长未知','计费重≤500g；物流≤收入25%；平台截止前24h缓冲','待补证','无运费无法算真实采购上限；目测尺寸不作证据',c['record_source']],
      ['完全成本','利润/利润率/最高采购价/压力利润均未知','≥20%且≥15元；组合压力≥0；报价≤采购上限','无法计算','03和04保留空白，不用公共示例费率补齐实际成本','03_逐品成本 / 04_费用明细'],
      ['500元与资金','测试单量、单品总成本、今日现金及未决损失未知','单品累计总成本≤500；全店应急≥5000、月损失≤4000','待补证','启动20,000元不是今天余额；候选不能独立重复用同一现金','05_500元与现金'],
      ['合规与权利','暂无逐SKU合规/图权/样品通过记录','禁限售/认证/承运/品牌外观/图片授权均明确通过','待补证','普通空收纳用途仅为方向筛选，不等于合规结论；'+extra,'O03/O04；'+c['record_source']]]
    normalized.append(dict(id=cid,name=c['name'],spec=c.get('specification_plan',c['name']+'，材质尺寸件数待核实'),priority=pr,market_url=c['market_url'],supply_url=url,fact=fact,inference=infer,difference=c.get('angle') or c.get('specification_plan'),gaps=missing,recommendation=pr+'：'+focus+'；取得主货源、完整成本后再判。',evidence_rows=ev,gates={k:'待补证' for k in ['data','demand','competition','supply','logistics','compliance','cash','rights']},model=None))

sources=[
 ['O01','菲律宾数字经济背景','PSA 2026-04-30发布：2025年数字经济GVA为2.74万亿PHP，占GDP9.8%，按现价较2024年增长5.4%。','官方事实','这是全国数字经济增加值，不是Shopee GMV。不能据此推出单品需求或利润。','https://psa.gov.ph/system/files/sad/Press%20Release_2025%20PDESA_0.pdf','2026-09-15'],
 ['O02','全国电商增加值','PSA图表列2025年电商GVA为8804.6亿PHP，占数字经济32.2%。','官方事实','这是电商增加值口径，不是交易总额，不代表Shopee独有份额。','https://psa.gov.ph/sites/default/files/infographics/Infographic_2025%20PDESA.pdf','2026-09-15'],
 ['O03','Shopee禁限售','当前公开政策把合法合规责任放在卖家；禁止/限制清单非穷尽且会更新。','官方规则','逐SKU对照；药物、受限设备等排除；无列表命中不代表已批准。','https://help.shopee.ph/portal/4/article/77276','2026-09-15'],
 ['O04','BPS强制认证','BPS要求受管制产品按PS/ICC方案具备相应标识。','官方规则','概述页写87，明细页编号到111；统计口径/更新可能不同，不写固定数量作为准入条件，以实际类别/规格清单为准。','https://bps.dti.gov.ph/product-certification/list-of-products-under-mandatory-certification','2026-09-15'],
 ['O05','菲律宾跨境收费','条款§23普通交易费列2.24%含VAT且取整比索；处理费每成功订单₱5、每月前50成功单豁免；境外卖家跨境佣金按另行通知。','官方规则','不能替代本店佣金、活动与结算费表；增长、平台运费计划等逐项确认适用。','https://help.shopee.ph/portal/4/article/77272','2026-09-15'],
 ['O06','平台整体背景','Sea披露2026Q2 Shopee整体订单42亿，同比增长27.5%；GMV383亿美元，同比增长28.4%。','发行人一手事实','覆盖Shopee整体经营地区，不能视为菲律宾站增速或份额。只作背景。','https://www.sec.gov/Archives/edgar/data/1703399/000119312526344596/d120948dex991.htm','2026-09-15'],
 ['O07','FDA监管边界','FDA有针对HUHS机构许可的官方办理材料；化学相关产品需要先判监管归类。','官方资料/经营排除','本次按用户约束排除化学相关；不是声称所有收纳品都需FDA许可。','https://www.fda.gov.ph/information-education-and-communication-iec-materials-relative-to-the-licensing-of-household-urban-hazardous-substances-huhs-establishments-covered-under-administrative-order-no-2019-0019-and-fd/','2026-09-15'],
 ['W01','公开店铺有限补证','Shopee Paccube公开页展示4件Packing Cubes ₱1050、5.0、239 sold；双面压缩款₱690、4.9、178 sold。','公开页面展示值','已售未说明时间窗；品牌本地制作，规格、配送、权利与跨境仿照不可比。不能计为30天样本；1050高于既有1000参考。','https://shopee.ph/paccube','2026-09-15'],
 ['L01','现有经营基线','非商城跨境/SLS；20,000启动资金；无销售库存；20%和15元门槛。','工作区历史记录','当前余额与店铺30天业绩仍缺；本次500元及60分钟要求优先。','Shopee菲律宾自动选品上架系统-主开发Prompt-v0.3.md','2026-09-15读取'],
 ['L02','历史市场/货源原始文件',f'{len(market)}条市场观测；{len(set(x["product_id"] for x in market))}个商品ID；{len(suppliers)}条供应商观测。','本地数据审计','采集于9月10/11日；币种、窗口及SKU报价问题未闭环。','evidence/input-manifest.json','2026-09-15审计'],
 ['T01','本轮源访问状态','Sorftime一次正常查询返回额度耗尽；1688网页未读取成功，浏览器策略阻止。','工具执行事实','未购买额度或绕过访问限制。只能完成已有证据部分。','source-log.json','2026-09-15']]

cash_rows=[
 ['单品预算','样品/拍摄等固定费+计划测试订单×每订单完全成本≤500','真实值未知','用户2026-09-15要求','广告、税、售后不遗漏；固定费与单件分摊不重复'],
 ['运行期预算','已发生+不可撤销承诺+拟新增+未决损失准备≤500','真实值未知','用户上限；经营控制建议','销售回款不抵消总测试成本；逐订单登记'],
 ['单品测试容量','floor((500−固定测试费)/单件完全成本)','待成本完整后计算','03_逐品成本Y列','不能用理想销售单量当固定费分摊分母'],
 ['一批10/20款上限','10×500=5000；20×500=10000','条件算例，非今日投入','用户测试上限×目标数量','审核候选数量不是每天同时付费测品数量'],
 ['新增现金额度','0.8×max(0,今日现金−应急金−既有未付承诺)','今日现金未知','历史保护金5000，80%经营规则','若20,000仍可用、无承诺，则0.8×(20,000−5,000)=12,000'],
 ['现金峰值','14/21/28天累计支付减已可用回款的最大缺口','回款分布未知','按订单与人民币可用到账日计算','短测试可先按28天无回款、所有拟付现金保守检验'],
 ['月亏损与风险容量','4000−已实现月损失−未决预计损失−本批最坏损失≥0','真实余额未知','历史月亏损硬上限4000','若现有损失0，每款最坏损失500，则最多8款全损风险；非默认授权'],
 ['收益目标量级','若完全成本后每单净利15，超过5000元需至少334单/月','条件推算，不是销量预测','floor(5000/15)+1=334','税和固定费用未完整时不能称真实净利'],
 ['不囤货仍有垫资','付款采购到回款前，货款与物流需要先支付','模式事实/资金影响推断','本店经营记录','跨期未回款、取消/拒收须进入预测，不假定当日循环'],
 ['500元与统计证据','预算最多支持的订单少于20时，成熟验证样本不足','不得自动加预算','经营复盘建议','可停止得出未证实；需要新预算时另行由店主决定']]
sop_rows=[
 ['0 建档','首次，独立计时','店铺类别/费率/物流/税/现金；3–5家供应商','形成有有效期的规则库与准确SKU模板','关键口径可核实','缺口只阻断相应结果'],
 ['1 每日刷新','Agent预处理','费用/库存/报价变更、候选历史','收50–100条线索、不同SPU去重','合法来源且时间可追溯','接口失败保留旧观测日期'],
 ['2 数据及合规','Agent预处理','PH商品/销售窗/权利/产品属性','币种、期间、规格、禁限售拦截','数据有效、合规明确','未知补证；明确违规排除'],
 ['3 需求竞争','Agent预处理','10–20同规格竞品、价格、店铺、评论','样本/店铺需求、CR3、到手价分位、差异验证','至少10款/5店、300件、3店30件；CR3≤70%等','不以全国增长/单链接累计已售替代'],
 ['4 供货利润','Agent预处理','1688逐SKU报价、包重、完整成本','基准+压力+采购上限+500元测试预算','20%且15元；压力≥0；测试≤500','未核实费用不填0；不能标通过'],
 ['5 组合审核','人工5分钟','当天现金、未决损失、候选风险','全店累计现金/亏损核查','应急5000；月上限4000；新增占资≤80%','冻结新增测试，不影响已有履约'],
 ['6 审市场证据','人工10分钟','Excel事实与竞争摘要','看有效样本、价格、跨境竞争、差异','证据足够支持小测','抽查疑点移出批审'],
 ['7 审供应成本','人工20分钟','22逐品/费用明细/样品证据','审可行报价、运费、预算、有效期','当前SKU/报价和压力通过','不因凑10个降低阈值'],
 ['8 批量人审','人工20分钟','证据完整的10–20不同SPU','记录批准/拒绝/补证与版本','所有硬门槛通过','关键输入变化旧批准失效'],
 ['9 存档','人工5分钟','审核记录与源快照','输出日报/Excel/待补证清单','审阅总时长60分钟目标','首次建库/等待报价另计'],
 ['10 复盘','7/14/28天','曝光、点击、访问、订单、售后、结算','验证漏斗与全队列成本；决定继续/停止','先在500元累计上限内执行；证据足够再讨论扩测','未成熟/零曝光不说产品无需求']]
next_rows=[
 ['P0 店铺费用','本店类目佣金/跨境费、支付、活动、增长、运费计划、固定/预售费；有效期','当前设置/官方通知；如有，提供3–5笔完整结算作对账','缺失','店主提供已有资料；不代填公共示例'],
 ['P0 SLS和云仓','渠道运费表、首续重/体积系数、净运费算法、贴标/包材/仓储、时效','只需当前用的一个仓和一个SLS渠道','缺失','费用和DTS/入仓截止一起核实'],
 ['P0 市场','PH/PHP明确的同规格10–20竞品/方向，独立店与30天窗口销量','来源/采集时间/统计开始结束；能区分本土/跨境与SKU销量','历史不合格','恢复已有数据源或提供合法导出'],
 ['P0 1688逐SKU','offer/SKU、规格件数、单件/阶梯价、MOQ/代发、库存、备货、包重、含税/运费','每款至少1主供应商；24小时内；建议备用1家','只有历史线索','不把0.03或0.6等起价当套装价'],
 ['P0 资金和经营','今天人民币可用余额、已付/未付承诺、当月损失、未决退件','近30天订单/销售/广告/退款及到账日；无则明确无','缺失','历史2万元不替代现金核验'],
 ['P1 样品/权利','测量、拉链/承重/耐用/适配等检查、商标外观/图片授权','按候选实际用途；仅空包/被动整理用品方向','未验证','用于关闭合规、质量、素材门槛'],
 ['复盘7天','上架可售、索引、曝光、点击','记录链接状态和时间，检查是否获得真实访问','尚未测试','零曝光时不作需求失败结论'],
 ['复盘14天','访问/订单/退款，来源拆分广告与自然','约100有效访问零单只作试行警报，排查价格与交运','尚未测试','所有测试支出累计到同SPU'],
 ['复盘28天','采购到实际可用人民币的全队列对账','成功、失败、取消、退货、待结算均保留；成熟订单建议≥20','尚未测试','预算不足以形成样本时，结论是未证实，不是成功']]

stats={'market_rows':len(market),'distinct_market_products':len(set(x['product_id'] for x in market)),
 'epoch_sales_date':sum(x.get('sales_calc_time')=='1970-01-01' for x in market),
 'negative_sales':sum(isinstance(x.get('sales_count'),(int,float)) and x['sales_count']<0 for x in market),
 'supplier_rows':len(suppliers),'zero_supplier_prices':sum(x.get('price')==0 for x in suppliers),
 'candidates':len(normalized),'candidates_with_supplier_lead':sum(bool(x['supply_url']) for x in normalized),
 'valid_market_rows_for_release':0,'eligible_candidates':0,'real_profit_verified':0}
data=dict(as_of=ASOF,candidates=normalized,sources=sources,observations=market,suppliers=suppliers,issues=issues,cash_rows=cash_rows,sop_rows=sop_rows,next_rows=next_rows,profile={'historical_capital_cny':20000,'current_available_cny':None,'test_total_cap_cny':500},stats=stats)
save(BASE/'selection.json',data)
save(BASE/'source-log.json',{'as_of':ASOF,'access':[{'tool':'Sorftime shopee_product_search_from_name','arguments':{'name':'travel organizer','site':'PH','page':1},'result':'MCP使用次数已达到上限，请升级您的套餐','effect':'只调用一次；无新增市场数据'}, {'tool':'web open','urls':['https://detail.1688.com/offer/847068328975.html','https://detail.1688.com/offer/625255182969.html'],'result':'不可读取'}, {'tool':'browser','url':'https://detail.1688.com/offer/847068328975.html','result':'站点安全策略阻止；无自动审批尝试；未绕过'}],'readable_public_sources':[r[5] for r in sources if r[5].startswith('https://')],'new_verified_sku_quotes':0,'new_eligible_candidates':0})
save(BASE/'data-audit.json',stats)
print(json.dumps(stats,ensure_ascii=False))
