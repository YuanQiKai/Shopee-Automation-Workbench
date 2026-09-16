"""Start the local workbench, checking the page and database before opening it."""
import ctypes
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager

R = Path(__file__).resolve().parents[1]
LOGS = R / 'data/logs'
PRIVATE = R / 'data/private'
STATE_FILE = PRIVATE / 'processes.json'
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
ENV = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUNBUFFERED': '1',
       'NEXT_TELEMETRY_DISABLED': '1', 'NO_PROXY': '127.0.0.1,localhost',
       'no_proxy': '127.0.0.1,localhost'}
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def listening(port):
    with socket.socket() as sock:
        sock.settimeout(.3)
        return sock.connect_ex(('127.0.0.1', port)) == 0


def process_identity(pid):
    """Read identity without signals: Windows os.kill(pid, 0) is unsafe."""
    if os.name != 'nt':
        return None
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return None
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
            return None
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return None
        size = wintypes.DWORD(32768)
        image = ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
            return None
        return {'image': image.value.casefold(),
                'created': (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime}
    finally:
        kernel.CloseHandle(handle)


def same_process(record):
    expected = record.get('identity') if record else None
    return bool(expected and process_identity(record['pid']) == expected)


@contextmanager
def startup_lock():
    """Repeated double-clicks must not start duplicate services."""
    import msvcrt
    with (PRIVATE / 'startup.lock').open('a+b') as handle:
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b'0')
            handle.flush()
        deadline = time.monotonic() + 90
        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('另一个启动正在进行，请稍后重试。')
                time.sleep(.5)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def wait_until(check, name, process=None, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process and process.poll() is not None:
            raise RuntimeError(f'{name} 启动退出，请查看 data/logs/{name}.log。')
        try:
            if check():
                return
        except (OSError, ValueError):
            pass
        time.sleep(.4)
    raise RuntimeError(f'{name} 未就绪，请查看 data/logs 中的日志。')


def request(path, json_body=False):
    with HTTP.open('http://127.0.0.1:' + path, timeout=5) as response:
        body = response.read()
        return json.loads(body) if json_body else response.status == 200


def healthy(port):
    data = request(f'{port}/api/health', True)
    return data.get('status') == 'ok' and data.get('database') == 'PostgreSQL' and data.get('scope') == 'PH'


def choose_node():
    bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    node = bundled if bundled.is_file() else shutil.which('node')
    if not node:
        raise RuntimeError('找不到 Node.js，请修复本地运行环境。')
    return node


def main():
    LOGS.mkdir(parents=True, exist_ok=True)
    PRIVATE.mkdir(parents=True, exist_ok=True)
    with startup_lock():
        node = choose_node()
        if not (R / 'frontend/.next/BUILD_ID').is_file():
            raise RuntimeError('缺少已构建的工作台页面，请先恢复前端构建。')
        print('[1/5] 正在检查本地数据库……', flush=True)
        subprocess.run([sys.executable, '-X', 'utf8', R / 'scripts/init_local.py'],
                       check=True, env=ENV, creationflags=FLAGS)
        states = json.loads(STATE_FILE.read_text(encoding='utf-8')) if STATE_FILE.exists() else []

        def spawn(name, args, port=None):
            nonlocal states
            if port and listening(port):
                return None
            with (LOGS / (name + '.log')).open('ab') as log:
                log.write(f'\n--- Startup {time.strftime("%Y-%m-%d %H:%M:%S")} ---\n'.encode())
                log.flush()
                process = subprocess.Popen([str(x) for x in args], cwd=R, env=ENV,
                                           stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                                           creationflags=FLAGS)
            record = {'name': name, 'pid': process.pid, 'port': port,
                      'identity': process_identity(process.pid)}
            states = [x for x in states if x['name'] != name] + [record]
            temporary = STATE_FILE.with_suffix('.tmp')
            temporary.write_text(json.dumps(states, indent=2), encoding='utf-8')
            temporary.replace(STATE_FILE)
            return process

        print('[2/5] 正在检查任务服务……', flush=True)
        process = spawn('temporal', [R / '.runtime/temporal/temporal.exe', 'server', 'start-dev',
                        '--ip', '127.0.0.1', '--port', '7239', '--ui-port', '8239',
                        '--db-filename', R / 'data/temporal.db'], 7239)
        wait_until(lambda: listening(7239), 'temporal', process)
        print('[3/5] 正在检查数据接口……', flush=True)
        process = spawn('api', [sys.executable, '-X', 'utf8', '-m', 'uvicorn', 'backend.app:app',
                        '--host', '127.0.0.1', '--port', '8010', '--no-access-log'], 8010)
        wait_until(lambda: healthy(8010), 'api', process)
        print('[4/5] 正在检查工作台页面……', flush=True)
        process = spawn('web', [node, R / 'frontend/node_modules/next/dist/bin/next', 'start',
                        R / 'frontend', '--hostname', '127.0.0.1', '--port', '3010'], 3010)
        wait_until(lambda: request('3010/') and healthy(3010), 'web', process)
        wait_until(lambda: isinstance(request('3010/api/bootstrap', True).get('candidates'), list),
                   'web', process)
        print('[5/5] 正在检查后台任务执行器……', flush=True)
        old = next((s for s in states if s['name'] == 'worker'), None)
        if not same_process(old):
            process = spawn('worker', [sys.executable, '-X', 'utf8', '-m', 'backend.worker'])
            time.sleep(2)
            if process.poll() is not None:
                raise RuntimeError('后台任务执行器启动失败，请查看 data/logs/worker.log。')
        print('工作台已就绪：http://127.0.0.1:3010', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as ex:
        print(f'启动未完成：{ex}', file=sys.stderr, flush=True)
        sys.exit(1)
