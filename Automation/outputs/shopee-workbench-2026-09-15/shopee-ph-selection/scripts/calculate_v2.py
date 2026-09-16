"""Run a single candidate's full-cost scenarios without approving it."""
import json,argparse
from pathlib import Path
from fees_v2 import compute
p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output');a=p.parse_args()
data=json.loads(Path(a.input).read_text(encoding='utf-8'),parse_float=str)
result={'base':compute(data['candidate'],data['settings']),'stress':compute(data['candidate'],data['settings'],True),'eligibility':'仍需检查市场、主备凭证、合规、时效与全店现金，计算器不能单独批准'}
text=json.dumps(result,ensure_ascii=False,indent=2)
if a.output:Path(a.output).write_text(text,encoding='utf-8')
else:print(text)
