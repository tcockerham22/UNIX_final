"""Ada's persistent skills: Markdown playbooks she can read and extend.

Each skill is a human-editable Markdown file in assets/skills with optional metadata:

    ---
    name: Coding
    description: Write, review, and debug code carefully.
    ---

    # Coding

    Instructions...

Skills are reference notes, not changes to the model's weights and not executable code.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SKILLS_DIR = ROOT / "assets" / "skills"
SLUG_RE = re.compile(r"[^a-z0-9]+")
FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class Skill:
    name: str
    description: str
    path: Path


class SkillStore:
    def __init__(self, directory: str | Path = DEFAULT_SKILLS_DIR):
        path = Path(directory)
        if not path.is_absolute():
            path = ROOT / path
        self.directory = path
        self.directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def slugify(name: str) -> str:
        slug = SLUG_RE.sub("-", name.strip().lower()).strip("-")
        return slug[:64] or "skill"

    @staticmethod
    def _parse(path: Path) -> tuple[str, str, str]:
        text = path.read_text(encoding="utf-8", errors="replace")
        name = ""
        description = ""
        body = text
        match = FRONT_MATTER.match(text)
        if match:
            body = text[match.end() :]
            for line in match.group(1).splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key = key.strip().lower()
                value = value.strip().strip('"').strip("'")
                if key == "name":
                    name = value
                elif key == "description":
                    description = value
        if not name:
            heading = re.search(r"^#\s+(.+)$", body, flags=re.MULTILINE)
            if heading:
                name = heading.group(1).strip()
        if not name:
            name = path.stem.replace("-", " ").title()
        if not description:
            for line in body.splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith(("#", "---", ">")):
                    description = stripped
                    break
        return name, description, body.strip()

    def _files(self) -> list[Path]:
        return sorted(path for path in self.directory.glob("*.md") if path.is_file())

    def list(self) -> list[Skill]:
        skills = []
        for path in self._files():
            name, description, _ = self._parse(path)
            skills.append(Skill(name=name, description=description, path=path))
        return sorted(skills, key=lambda skill: skill.name.lower())

    def index(self, limit: int = 40) -> str:
        skills = self.list()
        lines = []
        for skill in skills[:limit]:
            description = skill.description.strip()
            if len(description) > 140:
                description = description[:140].rstrip() + "…"
            lines.append(f"- {skill.name}: {description}")
        if len(skills) > limit:
            lines.append(f"- …and {len(skills) - limit} more")
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._files())

    def get(self, name: str) -> tuple[str, str] | None:
        needle = name.strip().lower()
        if not needle:
            return None
        for skill in self.list():
            keys = {skill.name.lower(), skill.path.stem.lower(), self.slugify(skill.name)}
            if needle in keys:
                _, _, body = self._parse(skill.path)
                return skill.name, body
        for skill in self.list():
            if needle in skill.name.lower() or needle in skill.path.stem.lower():
                _, _, body = self._parse(skill.path)
                return skill.name, body
        return None

    def save(
        self,
        name: str,
        description: str,
        instructions: str,
        replace: bool = False,
    ) -> str:
        name = " ".join(name.split()).strip()
        description = " ".join(description.split()).strip()
        instructions = instructions.strip()
        if not name:
            raise ValueError("skill name is required")
        if not instructions:
            raise ValueError("skill instructions are required")

        slug = self.slugify(name)
        path = self.directory / f"{slug}.md"
        if path.exists():
            existing_name, _, _ = self._parse(path)
            if existing_name.lower() != name.lower():
                suffix = hashlib.sha1(name.encode("utf-8")).hexdigest()[:6]
                path = self.directory / f"{slug}-{suffix}.md"

        existed = path.exists()
        if existed and not replace:
            existing = path.read_text(encoding="utf-8").rstrip()
            path.write_text(f"{existing}\n\n{instructions}\n", encoding="utf-8")
            return f"Appended to skill '{name}'."

        front = f"---\nname: {name}\ndescription: {description}\n---\n\n"
        body = instructions if instructions.lstrip().startswith("#") else f"# {name}\n\n{instructions}"
        path.write_text(front + body.rstrip() + "\n", encoding="utf-8")
        return f"Replaced skill '{name}'." if existed else f"Saved skill '{name}'."
