"""Run a real browser flow against an isolated SQLite fixture; never production."""
from pathlib import Path
import os,subprocess,sys,tempfile,time,urllib.request
ROOT=Path(__file__).resolve().parents[1]
def wait(url):
    for _ in range(100):
        try:
            with urllib.request.urlopen(url,timeout=2) as response:
                if response.status==200:return
        except Exception:time.sleep(.25)
    raise RuntimeError('Test server did not start: '+url)
def main():
    npm='npm.cmd' if os.name=='nt' else 'npm';env=os.environ.copy();env.update({'E2E_USERNAME':'e2e-admin','E2E_PASSWORD':'test-only-browser-password','E2E_BASE_URL':'http://localhost:5173','PYTHONPATH':str(ROOT/'backend')})
    with tempfile.TemporaryDirectory(prefix='intel-mini-test-') as temp:
        env['INTEL_TEST_DIRECTORY']=temp;servers=[]
        try:
            servers.append(subprocess.Popen([sys.executable,'-m','uvicorn','tests.browser_server:app','--host','127.0.0.1','--port','8000'],env=env,cwd=ROOT/'backend'))
            servers.append(subprocess.Popen([npm,'run','dev'],env=env,cwd=ROOT/'frontend'))
            wait('http://127.0.0.1:8000/api/health');wait('http://127.0.0.1:5173')
            return subprocess.call([npm,'run','test:e2e'],env=env,cwd=ROOT/'frontend')
        finally:
            for p in servers:p.terminate()
            for p in servers:
                try:p.wait(timeout=10)
                except subprocess.TimeoutExpired:p.kill()
if __name__=='__main__':raise SystemExit(main())
