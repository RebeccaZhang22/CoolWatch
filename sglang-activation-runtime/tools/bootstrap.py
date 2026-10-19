"""Rebuild the isolated editable source from a hash-pinned official wheel.

Usage: python tools/bootstrap.py --wheel /path/to/sglang-0.5.19-....whl
An existing dependency environment is read, never installed into or modified.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument("--wheel",type=Path,required=True)
parser.add_argument("--dependency-python",type=Path,
    default=ROOT.parent/"probe-runtime/.venv-sglang/bin/python")
args=parser.parse_args()
manifest=json.loads((ROOT/"upstream.json").read_text())
if hashlib.sha256(args.wheel.read_bytes()).hexdigest()!=manifest["sha256"]:
    raise SystemExit("Wheel hash differs from upstream.json; refusing a different base")
source=ROOT/".source"
if source.exists():
    raise SystemExit(".source already exists. Preserve your edits before rebuilding in a fresh directory.")
with zipfile.ZipFile(args.wheel) as archive:
    for name in archive.namelist():
        if name.startswith("sglang/") and not name.endswith("/"):
            relative=Path(name)
            if ".." in relative.parts:
                raise SystemExit("Unsafe wheel member")
            dest=source/relative
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(archive.read(name))
subprocess.run(["patch","--batch","--forward","-p1","-i",str(ROOT/"patches/activation-capture.patch")],
               cwd=source,check=True)
shutil.copytree(ROOT/"src",source,dirs_exist_ok=True)
# The isolated environment borrows dependency directories, not the original
# application's modules or its source tree. Its sglang import resolves to .source.
dependency_paths=json.loads(subprocess.check_output([str(args.dependency_python),"-c",
    "import json,sys; print(json.dumps([p for p in sys.path if p.endswith('site-packages')]))"],text=True))
subprocess.run([str(args.dependency_python),"-m","venv",str(ROOT/".venv")],check=True)
python=ROOT/".venv/bin/python"
site=Path(subprocess.check_output([str(python),"-c",
    "import sysconfig; print(sysconfig.get_path('purelib'))"],text=True).strip())
(site/"00-activation-runtime.pth").write_text(str(source)+"\n"+"\n".join(dependency_paths)+"\n")
print(f"Ready: {ROOT/'python'} (source: {source})")
