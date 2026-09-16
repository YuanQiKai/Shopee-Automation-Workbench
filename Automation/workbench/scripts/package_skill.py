from pathlib import Path
import shutil,json
R=Path(__file__).resolve().parents[1];S=R.parent/'outputs/shopee-workbench-2026-09-15/shopee-ph-selection'
(S/'assets').mkdir(exist_ok=True)
shutil.copyfile(R/'data/rules.json',S/'assets/philippines-rules.json')
code=(R/'backend/costs.py').read_text(encoding='utf-8').replace("ROOT/'data/rules.json'","ROOT/'assets/philippines-rules.json'")
(S/'scripts/fees_v2.py').write_text(code,encoding='utf-8')
test=(R/'tests/test_finance.py').read_text(encoding='utf-8')
test=test.replace("from backend.costs import compute,platform_shipping,logistics,warehouse,EXTRAS","from fees_v2 import compute,platform_shipping,logistics,warehouse,EXTRAS")
test=test.replace('from backend.domain import evaluate,current_hash,supplier_view','')
start=test.index('    ev=evaluate(c,s,[]);');end=test.index('def test_test_total',start)
test=test[:start]+test[end:]
(S/'scripts/test_fees_v2.py').write_text(test,encoding='utf-8')
for name in ('cost-model.md','data-contract.md'):
    p=S/'references'/name;s=p.read_text(encoding='utf-8');lines=s.splitlines();lines.insert(2,'> 兼容旧版资料；2026-09-15起双渠道、平台费、云仓、钱包、活动与新工作台输入以 [v2费用规则](logistics-and-fees-v2.md) 和 [Sorftime工作台契约](sorftime-workbench.md) 为准。不得重复累计旧处理费与新基础设施费。');p.write_text('\n'.join(lines)+'\n',encoding='utf-8')
p=S/'references/profile.md';s=p.read_text(encoding='utf-8');s+='\n## 2026-09-15新增确认\n\n标准国际、海运经济两渠道均开通COD；Shopee钱包提现0.2%；云仓默认价目2.5元/单含1种SKU。活动最低4折但资金承担方尚待确认；本店具体佣金/交易/项目费、当前现金、首次上架时间仍未补齐。参见v2规则，不使用历史启动预算推断今天余额。\n';p.write_text(s,encoding='utf-8')
print('Skill updated with self-contained rate table, cost engine and workbench client.')
