from pathlib import Path
import zipfile,json,hashlib
BASE=Path(__file__).resolve().parent
skill=BASE/'shopee-ph-selection';installed=Path('C:/Users/admin/.codex/skills/shopee-ph-selection')
files=[p for p in skill.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
for p in files:
    q=installed/p.relative_to(skill)
    assert q.exists() and hashlib.sha256(p.read_bytes()).digest()==hashlib.sha256(q.read_bytes()).digest()
include=['菲律宾Shopee每日选品审核.xlsx','分析结论与执行SOP.md','选品流程图.png','交付说明.md','selection.json','source-log.json','data-audit.json','数据质量复现.ipynb','qa/verification-results.json']
files += [BASE/p for p in include]
files += [p for p in (BASE/'evidence').rglob('*') if p.is_file()]
dest=BASE/'菲律宾选品SOP-Skill与Excel交付包.zip'
with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as z:
    for p in files:z.write(p,p.relative_to(BASE).as_posix())
with zipfile.ZipFile(dest) as z:assert z.testzip() is None
print(json.dumps({'zip':str(dest),'files':len(files),'bytes':dest.stat().st_size,'skill_installed':str(installed),'skill_files_verified':len(list(skill.rglob('*.py')))+len(list(skill.rglob('*.md')))},ensure_ascii=False))
