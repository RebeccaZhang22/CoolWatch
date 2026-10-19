"""Snapshot the exact FYH held-out membership and raw inference inputs.

Run with sudo only to read the source repository. Never modifies source files.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import zlib


EXPECTED = {"heldout_neulab": (139797, 81908), "heldout_ota": (238509, 141311),
            "heldout_swe": (23814, 13844)}
ARMS = ["arm1_ajonly", "arm2_neverneg", "arm3_swe", "arm4_ota", "arm5_neulab"]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repo", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--owner-uid", type=int, required=True)
    parser.add_argument("--owner-gid", type=int, required=True)
    args = parser.parse_args()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    os.chown(out, args.owner_uid, args.owner_gid)

    def save(name, data):
        path = out / name
        path.write_bytes(data)
        os.chown(path, args.owner_uid, args.owner_gid)
        return digest(data)

    root = args.source_repo / "results/probe_traces/merged_8b_randinj_20260924"
    manifest = {"source_repo": str(args.source_repo), "created_at_unix": time.time(),
                "files": {}, "expected": EXPECTED, "sampling_seed": 20261012}
    groups = None
    for arm in ARMS:
        path = root / f"datasets/{arm}_neulab_blind/partition.json"
        raw = path.read_bytes()
        manifest["files"][str(path)] = digest(raw)
        current = json.loads(raw)["eval_groups"]
        if groups is None:
            groups = current
            save("partition.json", raw)
        assert current == groups, f"Held-out membership differs for {arm}"
    assert set(groups) == set(EXPECTED)
    membership = {}
    by_gp = {}
    for face, gps in groups.items():
        for gp, ids in gps.items():
            assert isinstance(ids, list)
            for dp_id in ids:
                assert dp_id not in membership, f"Duplicate test ID: {dp_id}"
                membership[dp_id] = (face, gp)
                by_gp.setdefault(gp, set()).add(dp_id)
        assert sum(map(len, gps.values())) == EXPECTED[face][0]
    labels = {}
    label_path = root / "labels/risk_faced/labels.jsonl"
    label_hash = hashlib.sha256()
    with label_path.open("rb") as f:
        for raw in f:
            label_hash.update(raw)
            item = json.loads(raw)
            dp_id = item["decision_point_id"]
            if dp_id in membership:
                label = item["label"]
                assert label in (0, 1)
                assert dp_id not in labels or labels[dp_id] == label
                labels[dp_id] = label
    assert labels.keys() == membership.keys(), "Missing ground-truth labels"
    manifest["files"][str(label_path)] = label_hash.hexdigest()
    for name in ("runtime/message_content.py", "runtime/reasoning.py", "probes/featurization/features.py"):
        path = args.source_repo / "follow_your_heart" / name
        manifest["files"][str(path)] = save("reference_" + Path(name).name, path.read_bytes())
    database = out / "samples.sqlite"
    if database.exists():
        raise FileExistsError(f"Refusing to overwrite {database}")
    db = sqlite3.connect(database)
    os.chown(database, args.owner_uid, args.owner_gid)
    db.execute("PRAGMA journal_mode=TRUNCATE")
    db.execute("CREATE TABLE samples (id TEXT PRIMARY KEY, face TEXT, gp TEXT, label INTEGER, sample_order TEXT, raw BLOB)")
    counts = Counter()
    positive = Counter()
    started = time.monotonic()
    for gp, wanted in by_gp.items():
        directory = root / "grid_points" / gp
        if directory.is_symlink():
            target = os.readlink(directory)
            old = "/ssd/workspace/djs/follow-your-heart/"
            if target.startswith(old):
                directory = args.source_repo / target[len(old):]
            else:
                directory = directory.resolve()
        path = directory / "decision_points.jsonl"
        source_hash = hashlib.sha256()
        found = set()
        with path.open("rb") as f:
            for raw in f:
                source_hash.update(raw)
                item = json.loads(raw)
                dp_id = item["decision_point_id"]
                if dp_id not in wanted:
                    continue
                assert dp_id not in found, f"Repeated source row {dp_id}"
                assert item["grid_point_id"] == gp
                found.add(dp_id)
                face, _ = membership[dp_id]
                label = labels[dp_id]
                request = item.get("replay_request")
                assert request and request.get("messages"), f"Missing input {dp_id}"
                # Only actual model-visible content; no labels/provenance/attack hints.
                input_row = {"replay_request": {k: request[k] for k in ("messages", "tools") if k in request}}
                if item.get("prompt_token_ids"):
                    input_row["prompt_token_ids"] = item["prompt_token_ids"]
                encoded = json.dumps(input_row, ensure_ascii=False, separators=(",", ":")).encode()
                order = digest(("20261012:" + dp_id).encode())
                db.execute("INSERT INTO samples VALUES (?,?,?,?,?,?)",
                           (dp_id, face, gp, label, order, zlib.compress(encoded, level=1)))
                counts[face] += 1
                positive[face] += label
        assert found == wanted, f"{gp}: missing {len(wanted - found)} inputs"
        db.commit()
        manifest["files"][str(path)] = source_hash.hexdigest()
        print(json.dumps({"gp": gp, "exported": len(found), "total": sum(counts.values()),
                          "elapsed_seconds": round(time.monotonic() - started)}), flush=True)
    for face, (n, npos) in EXPECTED.items():
        assert (counts[face], positive[face]) == (n, npos)
    db.execute("CREATE INDEX sample_face_order ON samples(face,sample_order)")
    db.commit()
    db.close()
    manifest.update({"counts": dict(counts), "positive_counts": dict(positive), "complete": True,
                     "elapsed_seconds": time.monotonic() - started})
    save("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode())
    print(json.dumps({"complete": True, "counts": counts, "positive_counts": positive}), flush=True)


if __name__ == "__main__":
    main()
