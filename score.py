"""Track right/wrong answers as Claude grades them, tallied in blocks of 10.

    python score.py add <set_id> <n> <0|1>   # record one judged answer, print running tally
    python score.py summary <set_id>          # reprint the tally without adding anything
    python score.py reset <set_id>            # clear a set's log (asks nothing -- caller confirms)

<set_id> is the set's path under tests/ without the .json extension, e.g.
"hsk2/set_001" -- matches the "key" field gen.py writes into player_data.js, so
sets at different HSK levels never collide. Records live in
results/<set_id>.jsonl, one JSON object per line, in the order answers were
graded (not sentence order) so the block-of-10 view reflects the actual
session.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
RESULTS = ROOT / "results"

MASTERY_THRESHOLD = 0.9  # latest full block of 10 at >=90% (9/10 or 10/10) => stop here


def _path(set_id: str) -> Path:
    # set_id may contain a "/" (e.g. "hsk2/set_001"), which Path handles as a
    # subdirectory on every platform including Windows.
    return RESULTS / f"{set_id}.jsonl"


def load(set_id: str) -> list[dict]:
    path = _path(set_id)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def add(set_id: str, n: int, correct: bool) -> None:
    path = _path(set_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"n": n, "correct": correct}, ensure_ascii=False) + "\n")
    summarize(set_id)


def summarize(set_id: str) -> None:
    records = load(set_id)
    if not records:
        print(f"[{set_id}] no records yet")
        return

    total = len(records)
    correct = sum(1 for r in records if r["correct"])
    print(f"[{set_id}] {correct}/{total} correct overall ({correct / total:.0%})")

    last_full_block = None
    for i in range(0, total, 10):
        block = records[i : i + 10]
        c = sum(1 for r in block if r["correct"])
        marks = "".join("o" if r["correct"] else "x" for r in block)
        is_latest = i + len(block) == total
        tag = "  <- latest" if is_latest and len(block) < 10 else ""
        print(f"  {i + 1:>3}-{i + len(block):<3} {c}/{len(block)}  [{marks}]{tag}")
        if len(block) == 10:
            last_full_block = (i + 1, i + 10, c)

    if last_full_block:
        start, end, c = last_full_block
        if c / 10 >= MASTERY_THRESHOLD:
            print(f"  >> mastery reached: {start}-{end} scored {c}/10 (>= {MASTERY_THRESHOLD:.0%}). OK to stop here.")
        elif end == total:
            print(f"  >> {start}-{end} scored {c}/10 (< {MASTERY_THRESHOLD:.0%}). Keep going.")


def reset(set_id: str) -> None:
    path = _path(set_id)
    if path.exists():
        path.unlink()
    print(f"[{set_id}] cleared")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd, *rest = sys.argv[1:]
    if cmd == "add":
        set_id, n, correct = rest
        add(set_id, int(n), correct in ("1", "true", "True"))
    elif cmd == "summary":
        summarize(rest[0])
    elif cmd == "reset":
        reset(rest[0])
    else:
        sys.exit(f"unknown command: {cmd}")
