"""Copy this task's stopped database to a durable, ASCII-only user directory."""
from pathlib import Path
import json,subprocess,shutil,os
from datetime import datetime
R=Path(__file__).resolve().parents[1];f=R/'data/private/runtime.json';cfg=json.loads(f.read_text())
old=Path(cfg['pg_data']).resolve();oldbin=Path(cfg['pg_bin']).resolve();newroot=Path('C:/Users/admin/Documents/MeeyaLocal').resolve();new=newroot/'postgres'
expected=Path('C:/Users/admin/.codex/visualizations/2026/09/15/01a0a528-dd94-7f13-8680-2cc63961da91/meeya-local/postgres').resolve()
if old==new:print('Already in durable user data directory.');raise SystemExit
if old!=expected:raise RuntimeError('Source database path is not this task created database')
if new.exists():raise RuntimeError('Destination exists; will not overwrite it')
newroot.mkdir(parents=True,exist_ok=True);newbin=newroot/'pgsql/bin'
for part in ('bin','lib','share'):shutil.copytree(oldbin.parent/part,newroot/'pgsql'/part,dirs_exist_ok=True)
env={**os.environ,'PGPASSWORD':cfg['password']};flags=subprocess.CREATE_NO_WINDOW
backup=R/'data/private'/('database-backup-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.dump')
subprocess.run([str(oldbin/'pg_dump.exe'),'-h','127.0.0.1','-p','54329','-U','meeya','-d','meeya','-Fc','-f',str(backup)],env=env,creationflags=flags,check=True,timeout=30)
subprocess.run([str(oldbin/'pg_ctl.exe'),'-D',str(old),'stop','-m','fast'],creationflags=flags,check=True,timeout=30)
try:
    shutil.copytree(old,new)
    cfg.update(pg_bin=str(newbin),pg_data=str(new));f.write_text(json.dumps(cfg))
    with (newroot/'postgres-start.log').open('ab') as log:
        subprocess.run([str(newbin/'pg_ctl.exe'),'-D',str(new),'-l',str(newroot/'postgres.log'),'start'],cwd=newbin,creationflags=flags,check=True,stdout=log,stderr=log,timeout=30)
except Exception:
    cfg.update(pg_bin=str(oldbin),pg_data=str(old));f.write_text(json.dumps(cfg))
    with (old.parent/'restore-start.log').open('ab') as log:subprocess.run([str(oldbin/'pg_ctl.exe'),'-D',str(old),'-l',str(old.parent/'logs/postgres.log'),'start'],cwd=oldbin,creationflags=flags,stdout=log,stderr=log,timeout=30)
    raise
print('Database copied and started in C:/Users/admin/Documents/MeeyaLocal/postgres; old directory and a pg_dump backup retained.')
