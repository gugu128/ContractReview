from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
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
                print(f"[Skills-Error] 技能资源不完整，已跳过: {skill_dir.name}")
                continue
            try:
                metadata = self._parse_metadata(metadata_file)
                self._validate_metadata(skill_dir, metadata)
                executor_module = self._load_executor_module(skill_dir, executor_file.name)
                skill_id = str(metadata["id"])
                package = SkillPackage(
                    skill_id=skill_id,
                    version=str(metadata["version"]),
                    title=str(metadata.get("title", skill_id)),
                    description=str(metadata.get("description", "")),
                    triggers=list(metadata.get("triggers", [])),
                    path=skill_dir,
                    instructions=instructions_file.read_text(encoding="utf-8"),
                    executor_module=executor_module,
                )
                self.skills[skill_id] = package
                print(f"[Skills] 成功加载技能: {skill_id}")
            except Exception as exc:
                print(f"[Skills-Error] 技能加载失败，已跳过 {skill_dir.name}: {exc}")

    def get(self, skill_id: str) -> SkillPackage | None:
        return self.skills.get(skill_id)

    def _parse_metadata(self, metadata_file: Path) -> dict[str, Any]:
        try:
            yaml = import_module("yaml")
        except Exception as exc:
            raise ValueError(f"PyYAML 未安装: {exc}") from exc
        try:
            data = yaml.safe_load(metadata_file.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            raise ValueError(f"metadata.yaml 解析失败: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("metadata.yaml 必须是字典结构")
        return data

    def _validate_metadata(self, skill_dir: Path, metadata: dict[str, Any]) -> None:
        required_fields = ["id", "version", "instructions_file"]
        missing = [field for field in required_fields if not metadata.get(field)]
        if missing:
            raise ValueError(f"缺失关键字段: {', '.join(missing)}")
        instructions_file = skill_dir / str(metadata["instructions_file"])
        if not instructions_file.exists():
            raise ValueError(f"instructions_file 不存在: {instructions_file.name}")
        if str(metadata["id"]).strip() != skill_dir.name:
            raise ValueError(f"技能 id 与目录名不一致: {metadata['id']} != {skill_dir.name}")

    def _load_executor_module(self, skill_dir: Path, filename: str) -> Any:
        import importlib.util
        spec = importlib.util.spec_from_file_location(f"skills.{skill_dir.name}.executor", skill_dir / filename)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"无法加载技能执行脚本: {skill_dir}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
