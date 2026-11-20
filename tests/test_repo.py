"""The shipped files: Latch's eval keys, checksums, one rules text, and the repository's writing rules."""

import hashlib
import json
import subprocess
from pathlib import Path

from lab_automation_evals.environment import RULES_MD
from lab_automation_evals.tasks import ALL_TASKS

ROOT = Path(__file__).resolve().parents[1]
LATCH_KEYS = {"id", "canary", "task", "data_node", "grader", "metadata", "notes"}


def _tracked_text_files():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    except (subprocess.CalledProcessError, FileNotFoundError):
        out = []
    if not out:  # not a git checkout yet: fall back to the source tree
        out = [str(p.relative_to(ROOT)) for d in ("src", "tests", "docs", "evals", "results")
               for p in (ROOT / d).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
        out += [p.name for p in ROOT.glob("*.md")] + ["pyproject.toml"]
    return [ROOT / f for f in out if not f.endswith((".png", ".svg"))]


def test_eval_files_carry_latch_keys_and_true_checksums():
    manifest = json.loads((ROOT / "evals/manifest.json").read_text())
    assert [t["id"] for t in manifest["tasks"]] == [m.ID for m in ALL_TASKS]
    for t in manifest["tasks"]:
        rec = json.loads((ROOT / t["path"]).read_text())
        assert LATCH_KEYS <= set(rec)
        assert rec["canary"] == manifest["canary"]
        assert "<EVAL_ANSWER>" in rec["task"]
        for f in rec["data_files"]:
            data = (ROOT / f["path"]).read_bytes()
            assert hashlib.sha256(data).hexdigest() == f["sha256"] and len(data) == f["bytes"]


def test_one_rules_text_everywhere():
    assert (ROOT / "docs/ENVIRONMENT.md").read_text() == RULES_MD
    for m in ALL_TASKS:
        assert (ROOT / "evals" / m.ID / "workspace" / "environment.md").read_text() == RULES_MD


def test_prompts_do_not_leak_keys():
    leaks = {
        "la02_normalize_plate": ["B3", "D2", "F1"],
        "la04_find_the_error": ["step 5", "used_tip_contaminates_a_source` is"],
        "la05_dye_qc": ["channel 6", "46.9"],
        "la06_run_log_triage": ["C4", "E7", "H9"],
    }
    for task_id, needles in leaks.items():
        prompt = json.loads((ROOT / "evals" / task_id / "eval.json").read_text())["task"]
        for n in needles:
            assert n not in prompt, (task_id, n)


def test_writing_rules():
    # spelled in pieces so this file does not trip its own check
    banned = [chr(8212), "/" + "Users/", "cut" + "tag", "Co-" + "Authored-By", "Cap" + "able"]
    for path in _tracked_text_files():
        text = path.read_text()
        assert all(ord(ch) < 128 for ch in text), f"non-ASCII in {path}"
        for b in banned:
            assert b not in text, f"{b!r} in {path}"
