from pathlib import Path
import shutil,zipfile,hashlib,json
R=Path(__file__).resolve().parents[1];O=R.parent/'outputs/shopee-workbench-2026-09-15'
shutil.copyfile(R/'使用说明.md',O/'使用说明.md')
# Reviewable source and evidence, excluding runtimes, local secrets and database files.
skip={'.runtime','.venv','node_modules','.next','private','logs','postgres','__pycache__','.pytest_cache','exports'}
files=[]
with zipfile.ZipFile(O/'Meeya本地工作台与Skill源码.zip','w',zipfile.ZIP_DEFLATED) as z:
    for p in R.rglob('*'):
        rel=p.relative_to(R)
        if not p.is_file() or any(v in skip for v in rel.parts) or p.name.startswith('temporal.db') or p.suffix in ('.pyc','.tsbuildinfo') or p.name=='edb-page.html':continue
        z.write(p,'workbench/'+rel.as_posix());files.append({'path':'workbench/'+rel.as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    for p in (O/'shopee-ph-selection').rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts:z.write(p,'shopee-ph-selection/'+p.relative_to(O/'shopee-ph-selection').as_posix())
    z.write(O/'菲律宾选品工作台审核.xlsx','菲律宾选品工作台审核.xlsx')
(O/'source-manifest.json').write_text(json.dumps(files,ensure_ascii=False,indent=2),encoding='utf-8')
print('Packaged source, Skill and Excel; no keys or database/runtimes included.')
