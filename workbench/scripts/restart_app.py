"""Restart only the app/worker PIDs registered by this workspace."""
from pathlib import Path
import json,subprocess,sys
R=Path(__file__).resolve().parents[1];f=R/'data/private/processes.json';states=json.loads(f.read_text())
for x in states:
    if x['name'] in ('api','worker','web'):
        # Match command line to this exact workspace before stopping its process.
        ps="$p=Get-CimInstance Win32_Process -Filter 'ProcessId = "+str(int(x['pid']))+"'; if ($p -and $p.CommandLine.Contains('"+str(R).replace("'","''")+"')) { Stop-Process -Id "+str(int(x['pid']))+" -ErrorAction SilentlyContinue }"
        subprocess.run(['powershell.exe','-NoProfile','-Command',ps],creationflags=subprocess.CREATE_NO_WINDOW,check=False)
f.write_text(json.dumps([x for x in states if x['name'] not in ('api','worker','web')]))
subprocess.run([sys.executable,'-X','utf8',str(R/'scripts/start_local.py')],check=True)
