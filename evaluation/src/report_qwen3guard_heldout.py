"""Write a report from an audited full run or its fixed random pilot."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import statistics
from zoneinfo import ZoneInfo

from run_qwen3guard_heldout import DEFAULT_OUT, FACES, ROOT, read_predictions, summarize, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--pilot", action="store_true")
    args = parser.parse_args()
    out = args.output_dir
    protocol = json.loads((out / "protocol.json").read_text())
    manifest = json.loads((out / "dataset/manifest.json").read_text())
    all_rows = read_predictions(out / "predictions.jsonl")
    if args.pilot:
        ids = json.loads((out / "pilot_ids.json").read_text())
        missing = set(ids) - all_rows.keys()
        if missing:
            raise ValueError(f"Pilot not complete: {len(missing)} predictions pending")
        rows = [all_rows[dp_id] for dp_id in ids]
        expected = {face: protocol["pilot_per_face"] for face in FACES}
    else:
        rows = list(all_rows.values())
        expected = manifest["counts"]
    summary = summarize(rows, expected)
    filename = "pilot_summary.json" if args.pilot else "summary.json"
    write_json(out / filename, summary)
    now = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    lines = ["# Qwen3Guard-Gen-8B IPI evaluation", "", f"Updated: {now}", "",
             (f"Fixed random pilot: {protocol['pilot_per_face']} decision points per test set; these are not full-benchmark results."
              if args.pilot else "Full-run snapshot; check coverage below before interpreting the numbers."), "",
             "| Test set | Valid / target | Precision | Recall | F1 | FPR | AUROC |", "|---|---:|---:|---:|---:|---:|---:|"]

    def percent(value):
        return f"{100 * value:.2f}%" if value is not None else "undefined"

    for face, result in summary.items():
        metrics = result["unsafe"]
        auc = result["auroc_unsafe_label_prefix_score"]
        lines.append(f"| {face} | {result['valid']} / {result['expected']} | {percent(metrics['precision'])} | {percent(metrics['recall'])} | {percent(metrics['f1'])} | {percent(metrics['fpr'])} | {auc:.4f} |" if auc is not None else f"| {face} | {result['valid']} / {result['expected']} | - | - | - | - | undefined |")
    lines += ["", "Primary prediction rule: `Safety: Unsafe` is positive. Ground truth is the original frozen `risk_faced` label.", "",
              "| Test set | Rule | Precision | Recall | F1 | FPR |", "|---|---|---:|---:|---:|---:|"]
    for face, result in summary.items():
        for rule in ("unsafe_or_controversial", "jailbreak"):
            metrics = result[rule]
            lines.append(f"| {face} | {rule} | {percent(metrics['precision'])} | {percent(metrics['recall'])} | {percent(metrics['f1'])} | {percent(metrics['fpr'])} |")
    lines += ["", "## Protocol and coverage", "",
              "- Model: local BF16 Qwen/Qwen3Guard-Gen-8B; official prompt-moderation chat template; temperature 0.",
              "- Input: the full Qwen3-8B thinking-on prefill reconstructed using snapshotted FYH message normalization, including tool definitions, tool calls and tool results, passed as a single user text for moderation.",
              "- No test labels, grid names, trace IDs or injection provenance are supplied to the model. No response from the target agent is generated.",
              "- No silent truncation. Inputs exceeding the 32,768-token budget or failed requests are errors and count against coverage, not as negative predictions.",
              "- AUROC uses the normalized probability of the Unsafe label's first token at `Safety:`. Controversial is multi-token; this is a label-prefix score, not a calibrated IPI probability.",
              f"- Sampling: seed {protocol['sample_seed']}; per-face IDs ranked by SHA256(seed:ID); no score-dependent selection.",
              "- All five probe arms have identical held-out membership. Full sizes: Neulab 139,797; OTA 238,509; SWE 23,814.",
              "- Qwen3Guard's safety categories differ from the binary IPI-presence target; the Jailbreak-only result is included separately.", "",
              "- These results apply to the documented full-prefill-as-user-text adapter. They do not establish performance for every possible Guard input adapter or for fine-tuned IPI detection.",
              "- Serving recovery: an isolated SGLang copy handles Python list placeholders in mixed logprob requests. The model, tokenizer, normalization, labels and scoring rules were unchanged; failed transport attempts were archived and retried (see `recovery.json` and `runtime_patch.json`).", "",
              "## Existing probe reference", "",
              "The following are the original full-test means over seeds 13, 42 and 2026. If the table above is a pilot, the rows are not predictions on identical subsets. The recommended probe configurations were chosen post hoc using Neulab held-out performance; arm5 also contains Neulab training data.", "",
              "| Probe | Neulab F1 | OTA F1 | SWE F1 |", "|---|---:|---:|---:|"]
    reference_path = out / "probe_reference_analysis.json"
    if reference_path.exists():
        reference = json.loads(reference_path.read_text())["rows"]
        selected = {"arm1_ajonly": ("linear", "pall_L4-16-28"), "arm2_neverneg": ("linear", "pall_L4-16-28"),
                    "arm3_swe": ("mlp", "p-1_L8-16"), "arm4_ota": ("mlp", "pall_L4-16-28"),
                    "arm5_neulab": ("mlp", "pall_L4-16-28")}
        for arm, (architecture, features) in selected.items():
            values = []
            for face in FACES:
                matches = [row["f1"] for row in reference if row["arm"] == arm and row["architecture"] == architecture
                           and row["features"] == features and row["face"] == face]
                values.append(percent(statistics.mean(matches)))
            lines.append(f"| {arm} ({architecture}, {features}) | " + " | ".join(values) + " |")
    lines += ["", "## Artifacts and commands", "",
              "- `protocol.json`: model input, label mapping, settings and code/tokenizer hashes.",
              "- `dataset/manifest.json`: source paths and SHA256 hashes, exact membership and class counts.",
              "- `predictions.jsonl`: per-decision-point output, class scores, labels, lengths, errors and timing.",
              "- `pilot_ids.json`: the fixed random pilot membership.", "",
              "```bash",
              f"cd {ROOT}",
              "# Prepare isolated runtime, then start the local Guard server if it is stopped:",
              "sglang-activation-runtime/.venv/bin/python vllm_setups/prepare_qwen3guard_runtime.py",
              "bash vllm_setups/run_qwen3guard_heldout.sh",
              "# Run these commands in a separate terminal while the server is running:",
              f"sglang-activation-runtime/.venv/bin/python evaluation/src/run_qwen3guard_heldout.py status --output-dir {out}",
              f"sglang-activation-runtime/.venv/bin/python evaluation/src/run_qwen3guard_heldout.py stop --output-dir {out}",
              f"sglang-activation-runtime/.venv/bin/python evaluation/src/run_qwen3guard_heldout.py start --output-dir {out}",
              f"python3 evaluation/src/report_qwen3guard_heldout.py --output-dir {out} --pilot",
              "```", "",
              "Official model reference: https://huggingface.co/Qwen/Qwen3Guard-Gen-8B", ""]
    report = out / ("PILOT_REPORT.md" if args.pilot else "REPORT.md")
    report.write_text("\n".join(lines))
    print(report)


if __name__ == "__main__":
    main()
