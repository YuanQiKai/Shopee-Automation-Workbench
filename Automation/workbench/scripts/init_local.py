from pathlib import Path
import subprocess,json,secrets,os,shutil
R=Path(__file__).resolve().parents[1];P=R/'data/private';P.mkdir(exist_ok=True,parents=True)
pg=R/'.runtime/postgres/pgsql/bin';data=R/'data/postgres';logs=R/'data/logs';logs.mkdir(exist_ok=True)
if not str(R).isascii():
    portable=Path('C:/Users/admin/Documents/MeeyaLocal')
    portable.mkdir(parents=True,exist_ok=True)
    for component in ('bin','lib','share'):
        if not (portable/'pgsql'/component).exists():shutil.copytree(R/'.runtime/postgres/pgsql'/component,portable/'pgsql'/component,dirs_exist_ok=True)
    pg=portable/'pgsql/bin';data=portable/'postgres';logs=portable/'logs';logs.mkdir(exist_ok=True)
config=P/'runtime.json'
if not config.exists():
    secret=secrets.token_urlsafe(30)
    config.write_text(json.dumps({'database_url':'postgresql+psycopg://meeya:'+secret+'@127.0.0.1:54329/meeya','password':secret,'temporal_address':'127.0.0.1:7239'}))
cfg=json.loads(config.read_text());cfg.update(pg_bin=str(pg),pg_data=str(data));config.write_text(json.dumps(cfg));env={**os.environ,'PGPASSWORD':cfg['password']}
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
def run(args,check=True):
    if str(args[0]).endswith('pg_ctl.exe') and 'start' in args:
        with (logs/'pg-control.log').open('ab') as f:
            p=subprocess.run([str(x) for x in args],cwd=pg,env=env,creationflags=flags,stdout=f,stderr=f,timeout=45)
        p.stdout=b'';p.stderr=b''
    else:p=subprocess.run([str(x) for x in args],cwd=pg,env=env,creationflags=flags,capture_output=True,timeout=20)
    if check and p.returncode:
        print(p.stdout.decode('utf-8',errors='replace'));print(p.stderr.decode('utf-8',errors='replace'));raise RuntimeError('PostgreSQL启动步骤失败')
    return p
if not (data/'PG_VERSION').exists():
    pw=data.parent/'init-password.tmp';pw.write_text(cfg['password'])
    try:
        r=run([pg/'initdb.exe','-D',data,'-U','meeya','--pwfile',pw,'--auth=scram-sha-256','--encoding=UTF8','--locale=C'])
    finally:pw.unlink(missing_ok=True)
    with (data/'postgresql.conf').open('a') as f:f.write("\nlisten_addresses = '127.0.0.1'\nport = 54329\n")
status=run([pg/'pg_ctl.exe','-D',data,'status'],False)
if status.returncode:run([pg/'pg_ctl.exe','-D',data,'-l',logs/'postgres.log','start'])
r=run([pg/'psql.exe','-h','127.0.0.1','-p','54329','-U','meeya','-d','postgres','-tAc',"SELECT 1 FROM pg_database WHERE datname='meeya'" ])
if b'1' not in r.stdout:run([pg/'createdb.exe','-h','127.0.0.1','-p','54329','-U','meeya','meeya'])
print('PostgreSQL ready on 127.0.0.1:54329; credentials saved privately, not printed.')
