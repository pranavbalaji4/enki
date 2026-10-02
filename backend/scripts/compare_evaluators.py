"""Measure the understanding judges against hand-labelled turns before trusting them.

Input: a JSONL file, one turn per line:
  {"question": "...", "reply": "<tutor output>", "next": "<learner's next message>", "label": "understood|iffy|not_understood"}

Usage (from backend/):
  python scripts/compare_evaluators.py labelled_turns.jsonl            # every judge that has credentials
  python scripts/compare_evaluators.py labelled_turns.jsonl --only jev

Reports accuracy, a confusion table, and (for Jev, which returns a distribution) the Brier score — lower is better
calibrated. Each turn costs one call per judge."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from enki.config import settings  # noqa: E402
from enki.evaluators import ClaudeEvaluator, JevEvaluator, Judgement  # noqa: E402
from enki.taxonomy import LEVELS  # noqa: E402


def level_of(j: Judgement) -> str:
    if j.level_probs:
        return LEVELS[max(range(len(LEVELS)), key=lambda i: j.level_probs[i])]
    # Claude gives one number; bucket it the way the chat UI colours it.
    return "understood" if j.understanding >= 0.7 else "iffy" if j.understanding >= 0.45 else "not_understood"


def brier(j: Judgement, label: str) -> float | None:
    if not j.level_probs:
        return None
    return sum((p - (1.0 if LEVELS[i] == label else 0.0)) ** 2 for i, p in enumerate(j.level_probs))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--only", choices=["jev", "claude"])
    args = ap.parse_args()

    turns = [json.loads(line) for line in Path(args.path).read_text(encoding="utf-8").splitlines() if line.strip()]
    bad = [t for t in turns if t.get("label") not in LEVELS]
    if bad:
        sys.exit(f"{len(bad)} line(s) have a label outside {LEVELS}")

    judges = {}
    if args.only in (None, "jev") and settings.typesafe_api_key:
        judges["jev"] = JevEvaluator()
    if args.only in (None, "claude"):
        judges["claude"] = ClaudeEvaluator()
    if not judges:
        sys.exit("No judge available (set TYPESAFE_API_KEY for Jev).")

    for name, judge in judges.items():
        confusion: Counter = Counter()
        briers = []
        for t in turns:
            j = judge.judge(t["question"], t["reply"], t["next"])
            confusion[(t["label"], level_of(j))] += 1
            if (b := brier(j, t["label"])) is not None:
                briers.append(b)
        correct = sum(n for (gold, pred), n in confusion.items() if gold == pred)
        print(f"\n== {name}: {correct}/{len(turns)} correct ({correct / len(turns):.0%})")
        header = "label / predicted"
        print(f"{header:>18} " + " ".join(f"{lv:>15}" for lv in LEVELS))
        for gold in LEVELS:
            print(f"{gold:>18} " + " ".join(f"{confusion[(gold, pred)]:>15}" for pred in LEVELS))
        if briers:
            print(f"Brier score: {sum(briers) / len(briers):.3f}  (0 = perfect, 0.667 = uniform guessing)")


if __name__ == "__main__":
    main()
