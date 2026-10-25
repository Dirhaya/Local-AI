"""Explicitly allowlisted code-only release. Never package a user's working directory wholesale."""
import argparse,json
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
ROOT=Path(__file__).resolve().parent.parent
TOP={'run.py','version.json','publisher.json','requirements.txt','requirements-speech.txt','requirements-dev.txt','LICENSE','README.md','INTEGRATIONS.md','START-HERE.txt','VERIFICATION.md','STUDY-GUIDE.md','ARCHITECTURE.md','Start-Windows.cmd','SETUP-EVERYTHING.cmd','Setup-Local-Model-Windows.cmd','Install-Speech-Windows.cmd','Check-Windows.cmd'}
def build(output):
 output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
 paths=[p for p in ROOT.iterdir() if p.is_file() and p.name in TOP]
 for directory in ('app','scripts','tests'):
  paths.extend(p for p in (ROOT/directory).rglob('*') if p.is_file() and not any(part.startswith('.') or part=='__pycache__' for part in p.relative_to(ROOT).parts) and p.suffix in ('.py','.js','.cjs','.css','.html','.ps1'))
 with ZipFile(output,'w',compression=ZIP_DEFLATED) as archive:
  for path in sorted(set(paths)):
   raw=path.read_bytes()
   if path.suffix in ('.cmd','.ps1'):raw=raw.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
   archive.writestr('sultan-local-ai/'+path.relative_to(ROOT).as_posix(),raw)
 return output
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'release-output'/'Sultan-Local-AI-Windows.zip');args=parser.parse_args()
 print(build(args.output))
