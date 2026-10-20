"""Load prompt versions from the prompts/ folder."""

from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


def load_prompt(version: str) -> str:
    """load_prompt("extract_v1") reads prompts/extract_v1.md"""
    return (PROMPTS_DIR / f"{version}.md").read_text(encoding="utf-8").strip()
