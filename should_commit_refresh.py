import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VOLATILE_PATTERNS = [
    (re.compile(r'"generated_at":\s*"[^"]+"'), '"generated_at":"<volatile>"'),
    (re.compile(r'"recorded_at":\s*"[^"]+"'), '"recorded_at":"<volatile>"'),
    (re.compile(r"数据更新：\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"), "数据更新：<volatile>"),
    (re.compile(r"最近更新：\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"), "最近更新：<volatile>"),
]


def git_changed_files() -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
    )
    files = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append(path.strip('"'))
    return files


def git_show_head(path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def normalize_json_text(text: str) -> str:
    payload = json.loads(text)
    strip_volatile(payload)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def strip_volatile(value: object) -> None:
    if isinstance(value, dict):
        for key in list(value):
            if key in {"generated_at", "recorded_at"}:
                value[key] = "<volatile>"
            else:
                strip_volatile(value[key])
    elif isinstance(value, list):
        for item in value:
            strip_volatile(item)


def normalize_text(path: str, text: str) -> str:
    if path.endswith(".json"):
        try:
            return normalize_json_text(text)
        except json.JSONDecodeError:
            pass
    for pattern, replacement in VOLATILE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def should_commit() -> bool:
    changed = git_changed_files()
    if not changed:
        return False
    for path in changed:
        current_path = ROOT / path
        if not current_path.exists():
            return True
        previous = git_show_head(path)
        if previous is None:
            return True
        current = current_path.read_text(encoding="utf-8")
        if normalize_text(path, previous) != normalize_text(path, current):
            return True
    return False


def main() -> int:
    if should_commit():
        print("commit needed")
        return 0
    print("only volatile refresh timestamps changed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
