from pathlib import Path
p=Path(__file__).resolve().parents[1]/'frontend/app/page.tsx'
s=p.read_text(encoding='utf-8').replace('Number(Boolean(c.data.primary))','Number(Boolean(c.data.primary?.sku_id))').replace('Number(Boolean(c.data.backup))','Number(Boolean(c.data.backup?.sku_id))')
p.write_text(s,encoding='utf-8')
