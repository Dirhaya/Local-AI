"""Run locally with one process; never bind to the LAN."""
import os
import json
from pathlib import Path
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

os.environ.setdefault("OLLAMA_NO_CLOUD", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("DO_NOT_TRACK", "1")

# Setup saves only model/path preferences here, never credentials or private content.
preferences = Path(__file__).parent / "setup-defaults.json"
if preferences.is_file():
    try:
        defaults = json.loads(preferences.read_text(encoding="utf-8-sig"))
        for field, variable in (("model", "SULTAN_DEFAULT_MODEL"), ("speech_model_path", "SULTAN_DEFAULT_SPEECH_PATH")):
            if isinstance(defaults.get(field), str):
                os.environ.setdefault(variable, defaults[field])
    except (OSError, ValueError):
        pass


def main():
    if sys.version_info < (3, 11):
        raise SystemExit("Install Python 3.11 or 3.12 first.")
    address = "http://127.0.0.1:8765"
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", 8765))
    except OSError:
        raise SystemExit("Port 8765 is busy. Close an existing instance of Sultan Local AI and try again.")
    finally:
        probe.close()

    if not os.environ.get('SULTAN_LAUNCH_DELEGATED'):
        import subprocess
        from app.update_engine import UpdateManager
        data_root=Path(os.environ.get('SULTAN_DATA_DIR') or Path(os.environ.get('LOCALAPPDATA',Path.home()/'.local'/'share'))/'SultanLocalAI')
        updater=UpdateManager(data_root,Path(__file__).parent)
        try:
            updater.activate_pending()
        except Exception as exc:
            print(f'Update was not activated: {exc}. Starting the installed app instead.')
        target=updater.target()
        if target:
            interpreter=target/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
            env={**os.environ,'SULTAN_LAUNCH_DELEGATED':'1','SULTAN_BOOTSTRAP_ROOT':str(Path(__file__).parent)}
            result=subprocess.run([str(interpreter),str(target/'run.py')],cwd=target,env=env)
            if result.returncode==0:return
            print('Updated app exited with an error. Reverting the code selection; personal data is preserved.')
            updater.rollback()

    import uvicorn
    from app.main import app

    def open_when_ready():
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(30):
            try:
                with opener.open(address + "/api/status", timeout=1) as response:
                    if response.status == 200:
                        webbrowser.open(address)
                        return
            except OSError:
                time.sleep(0.4)

    threading.Thread(target=open_when_ready, daemon=True).start()
    print(f"\nSultan Local AI: {address}\nVault: {app.state.vault.directory}\nKeep this window open. Press Ctrl+C to stop.\n")
    uvicorn.run(app, host="127.0.0.1", port=8765, workers=1, proxy_headers=False, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
