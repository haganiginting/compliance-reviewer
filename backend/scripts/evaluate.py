from __future__ import annotations

import argparse
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import EVALS_DIR  # noqa: E402
from app.evals import run_eval  # noqa: E402


def main() -> None:
    args = _parse_args()
    output = run_eval(config_path=_resolve_path(args.config), output_dir=args.output_dir)
    totals = output["totals"]

    print(f"Eval complete: {totals['samples']} sample(s)")
    print(f"  Caught: {totals['caught']}")
    print(f"  Missed: {totals['missed']}")
    print(f"  Unexpected issues: {totals['unexpected_issues']}")
    print(f"  Wording violations: {totals['wording_violations']}")
    print(f"  Results saved to: {output['output_path']}")

    for sample in output["samples"]:
        print(f"\n{sample['sample']} - {sample['status']}")
        if sample["status"] == "error":
            print(f"  Error: {sample['error']}")
        print(f"  Caught: {len(sample['caught'])}")
        print(f"  Missed: {len(sample['missed'])}")
        print(f"  Unexpected issues: {len(sample['unexpected_issues'])}")
        print(f"  Wording violations: {len(sample['wording_violations'])}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run known-answer compliance reviews and report caught/missed findings."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=EVALS_DIR / "expected_findings.json",
        help="Path to the private expected-findings JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional directory for eval result JSON. Defaults to backend/data/evals/results.",
    )
    return parser.parse_args()


def _resolve_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute() or expanded.exists():
        return expanded

    backend_relative = BACKEND_DIR / expanded
    if backend_relative.exists():
        return backend_relative

    repo_relative = BACKEND_DIR.parent / expanded
    if repo_relative.exists():
        return repo_relative

    return expanded


if __name__ == "__main__":
    main()
