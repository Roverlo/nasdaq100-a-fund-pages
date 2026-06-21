import py_compile
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
GENERATOR = ROOT / "generate_nasdaq_fund_table.py"
PREPARE_PAGES = ROOT / "prepare_github_pages.py"
VALIDATOR = ROOT / "validate_refresh_outputs.py"
COMMIT_GUARD = ROOT / "should_commit_refresh.py"


def run_step(args: list[str], *, retries: int = 0) -> None:
    last_error: subprocess.CalledProcessError | None = None
    for attempt in range(retries + 1):
        try:
            subprocess.run(args, cwd=ROOT, check=True)
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(10)
    assert last_error is not None
    raise last_error


def main() -> int:
    py_compile.compile(str(GENERATOR), doraise=True)
    run_step([sys.executable, str(GENERATOR), "--output-dir", str(ROOT)], retries=1)
    run_step([sys.executable, str(PREPARE_PAGES)])
    py_compile.compile(str(VALIDATOR), doraise=True)
    py_compile.compile(str(COMMIT_GUARD), doraise=True)
    run_step([sys.executable, str(VALIDATOR)])
    print("refresh pipeline completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
