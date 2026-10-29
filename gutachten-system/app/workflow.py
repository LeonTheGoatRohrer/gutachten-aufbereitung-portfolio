from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .storage import WORKFLOW_DIR


@dataclass
class WorkflowStep:
    id: str
    title: str
    instruction_path: Path
    review_path: Path
    instruction: str
    review_prompt: str


def title_from_id(step_id: str) -> str:
    raw = step_id
    if "_" in raw:
        raw = raw.split("_", 1)[1]
    return raw.replace("_", " ").title()


def load_steps() -> list[WorkflowStep]:
    WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)
    steps: list[WorkflowStep] = []
    for instruction_path in sorted(WORKFLOW_DIR.glob("*.md")):
        if instruction_path.name.endswith(".check.md"):
            continue
        step_id = instruction_path.stem
        review_path = instruction_path.with_name(f"{step_id}.check.md")
        steps.append(
            WorkflowStep(
                id=step_id,
                title=title_from_id(step_id),
                instruction_path=instruction_path,
                review_path=review_path,
                instruction=instruction_path.read_text(encoding="utf-8"),
                review_prompt=review_path.read_text(encoding="utf-8") if review_path.exists() else "",
            )
        )
    return steps


def load_step(step_id: str) -> WorkflowStep:
    for step in load_steps():
        if step.id == step_id:
            return step
    raise FileNotFoundError(step_id)


def save_step(step_id: str, instruction: str, review_prompt: str) -> WorkflowStep:
    WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)
    instruction_path = WORKFLOW_DIR / f"{step_id}.md"
    review_path = WORKFLOW_DIR / f"{step_id}.check.md"
    instruction_path.write_text(instruction, encoding="utf-8")
    review_path.write_text(review_prompt, encoding="utf-8")
    return load_step(step_id)
