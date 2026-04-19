from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SkillPackage:
    skill_id: str
    version: str
    title: str
    description: str
    triggers: list[str]
    path: Path
    instructions: str
    executor_module: Any


class SkillManager:
    def __init__(self, skills_root: str | Path = "skills") -> None:
        self.skills_root = Path(skills_root)
        self.skills: dict[str, SkillPackage] = {}
        self.load_skills()

    def load_skills(self) -> None:
        if not self.skills_root.exists():
            return
        for skill_dir in self.skills_root.iterdir():
            if not skill_dir.is_dir():
                continue
            metadata_file = skill_dir / "metadata.yaml"
            instructions_file = skill_dir / "instructions.md"
            executor_file = skill_dir / "executor.py"
            if not metadata_file.exists() or not instructions_file.exists() or not executor_file.exists():
                continue
            metadata = self._parse_metadata(metadata_file)
            if not metadata:
                continue
            skill_id = metadata.get("id", skill_dir.name)
            executor_module = self._load_executor_module(skill_dir, executor_file.name)
            package = SkillPackage(
                skill_id=skill_id,
                version=metadata.get("version", "0.0.0"),
                title=metadata.get("title", skill_id),
                description=metadata.get("description", ""),
                triggers=metadata.get("triggers", []),
                path=skill_dir,
                instructions=instructions_file.read_text(encoding="utf-8"),
                executor_module=executor_module,
            )
            self.skills[skill_id] = package
            print(f"[Skills] 成功加载技能: {skill_id}")

    def get(self, skill_id: str) -> SkillPackage | None:
        return self.skills.get(skill_id)

    def _parse_metadata(self, metadata_file: Path) -> dict[str, Any]:
        data: dict[str, Any] = {}
        current_list_key: str | None = None
        for raw_line in metadata_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("-") and current_list_key:
                data.setdefault(current_list_key, []).append(line.lstrip("- ").strip())
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()
                current_list_key = key if value == "" else None
                if value:
                    data[key] = value
                else:
                    data.setdefault(key, [])
        return data

    def _load_executor_module(self, skill_dir: Path, filename: str) -> Any:
        import importlib.util
        spec = importlib.util.spec_from_file_location(f"skills.{skill_dir.name}.executor", skill_dir / filename)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"无法加载技能执行脚本: {skill_dir}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
