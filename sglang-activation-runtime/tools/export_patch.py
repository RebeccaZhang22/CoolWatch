"""Maintainer utility: record edits to the official source as a reviewable patch."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument("--wheel",type=Path,required=True)
args=parser.parse_args()
manifest=json.loads((ROOT/"upstream.json").read_text())
assert hashlib.sha256(args.wheel.read_bytes()).hexdigest()==manifest["sha256"]
patch=[]
with zipfile.ZipFile(args.wheel) as z:
    for name in sorted(z.namelist()):
        if name.startswith("sglang/") and name.endswith(".py"):
            before=z.read(name).decode().replace("\r\n", "\n")
            after=(ROOT/".source"/name).read_text()
            if before!=after:
                patch.extend(difflib.unified_diff(before.splitlines(True),after.splitlines(True),
                    fromfile="a/"+name,tofile="b/"+name))
(ROOT/"patches/activation-capture.patch").write_text("".join(patch))
print(f"Wrote {len(patch)} patch lines")
