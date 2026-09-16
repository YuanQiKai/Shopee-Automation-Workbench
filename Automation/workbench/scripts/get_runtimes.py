import urllib.request, re, json, zipfile, hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
root=Path(__file__).resolve().parents[1]/'.runtime'
root.mkdir(exist_ok=True)
def get(url):
    return urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Meeya-Local-Setup/0.4'}),timeout=90)
def install(kind,url):
    path=root/(kind+'.zip')
    if not path.exists():
        with get(url) as r,path.open('wb') as f:
            while chunk:=r.read(1024*1024): f.write(chunk)
    with zipfile.ZipFile(path) as z: z.extractall(root/kind)
    print(json.dumps({'kind':kind,'url':url,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}),flush=True)
page=get('https://www.enterprisedb.com/download-postgresql-binaries').read().decode()
urls=sorted(set(re.findall(r'https[^\s\"<>]+windows-x64-binaries.zip',page)))
pg='https://sbp.enterprisedb.com/getfile.jsp?fileid=1260491'
release=json.load(get('https://api.github.com/repos/temporalio/cli/releases/latest'))
temporal=next(x['browser_download_url'] for x in release['assets'] if 'windows_amd64' in x['name'] and x['name'].endswith('.zip'))
print(json.dumps({'postgres':pg,'temporal':temporal}),flush=True)
with ThreadPoolExecutor(max_workers=2) as pool:
    list(pool.map(lambda a:install(*a),[('postgres',pg),('temporal',temporal)]))
