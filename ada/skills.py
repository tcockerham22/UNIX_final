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
    updated: float = 0.0
    sources: list[str] | None = None


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
    def _parse(path: Path) -> tuple[str, str, str, float, list[str]]:
        text = path.read_text(encoding="utf-8", errors="replace")
        name = ""
        description = ""
        updated = 0.0
        sources: list[str] = []
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
                elif key == "updated":
                    try:
                        updated = float(value)
                    except ValueError:
                        updated = 0.0
                elif key == "sources":
                    # simple comma/semicolon separated list
                    sources = [s.strip() for s in re.split(r"[;,]", value) if s.strip()]
        if not updated:
            try:
                updated = path.stat().st_mtime
            except OSError:
                updated = 0.0
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
        return name, description, body.strip(), updated, sources

    def _files(self) -> list[Path]:
        return sorted(path for path in self.directory.glob("*.md") if path.is_file())

    def list(self) -> list[Skill]:
        skills = []
        for path in self._files():
            name, description, _, updated, sources = self._parse(path)
            skills.append(Skill(name=name, description=description, path=path, updated=updated, sources=sources))
        return sorted(skills, key=lambda skill: skill.name.lower())

    def list_info(self) -> list[dict]:
        items = []
        for s in self.list():
            items.append({
                "name": s.name,
                "description": s.description,
                "updated": s.updated,
                "sources": s.sources or [],
                "path": str(s.path),
            })
        return items

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
                n, _, body, _, _ = self._parse(skill.path)
                return n, body
        for skill in self.list():
            if needle in skill.name.lower() or needle in skill.path.stem.lower():
                n, _, body, _, _ = self._parse(skill.path)
                return n, body
        return None

    def save(
        self,
        name: str,
        description: str,
        instructions: str,
        replace: bool = False,
        sources: list[str] | None = None,
    ) -> str:
        import time as _time
        name = " ".join(name.split()).strip()
        description = " ".join(description.split()).strip()
        instructions = instructions.strip()
        if not name:
            raise ValueError("skill name is required")
        if not instructions:
            raise ValueError("skill instructions are required")

        low = instructions.lower()
        bad_phrases = [
            "web_search",
            "web_fetch",
            "find reliable sources",
            "save relevant information",
            "research basics",
            "research it",
            "gather reliable facts",
            "synthesize what you learned",
            "go and research",
            "stay updated",
            "learn more about",
            "learn everything about",
            "learn all you can",
            "research different types",
            "research everything",
            "document the most common",
            "create a comprehensive guide",
            "create a guide",
            "and document",
            "read_skill for specific skills",
        ]
        meta_hits = sum(1 for p in bad_phrases if p in low)
        # also catch plans/meta-instructions without real substance
        starts_meta = low.lstrip("# ").startswith(("learn ", "research ", "study ", "document ", "create ", "gather "))
        lines = [ln.strip() for ln in instructions.splitlines() if ln.strip()]
        has_structure = sum(1 for ln in lines if ln.startswith(("-", "*", "1.", "2.", "3.", "#"))) >= 2
        substantive = (len(instructions) >= 220 and (len(lines) >= 4 or has_structure or ":" in instructions or ";" in instructions))
        too_short = len(instructions) < 220
        too_meta = (meta_hits >= 1 and len(instructions) < 900) or (starts_meta and meta_hits >= 1 and len(instructions) < 1200)
        if too_short or too_meta or (not substantive and len(instructions) < 500):
            raise ValueError(
                "skill instructions are too vague or meta. First use web_search/web_fetch to gather facts, then call save_skill "
                "again with the actual learned content itself: key concepts/definitions, how it works, concrete steps/examples/commands, "
                "protocols/components, use cases, and limitations/pitfalls. Do not tell a future reader to search, fetch, research, or create a guide; "
                "write the knowledge (aim for substantial, detailed, useful notes)."
            )

        slug = self.slugify(name)
        path = self.directory / f"{slug}.md"
        if path.exists():
            existing_name, _, _, _, _ = self._parse(path)
            if existing_name.lower() != name.lower():
                suffix = hashlib.sha1(name.encode("utf-8")).hexdigest()[:6]
                path = self.directory / f"{slug}-{suffix}.md"

        existed = path.exists()
        if existed and not replace:
            existing = path.read_text(encoding="utf-8").rstrip()
            path.write_text(f"{existing}\n\n{instructions}\n", encoding="utf-8")
            return f"Appended to skill '{name}'."

        src_line = ""
        if sources:
            clean = [s.strip() for s in sources if s and s.strip()][:8]
            if clean:
                src_line = f"sources: {', '.join(clean)}\n"
        front = f"---\nname: {name}\ndescription: {description}\nupdated: {_time.time():.0f}\n{src_line}---\n\n"
        body = instructions if instructions.lstrip().startswith("#") else f"# {name}\n\n{instructions}"
        path.write_text(front + body.rstrip() + "\n", encoding="utf-8")
        return f"Replaced skill '{name}'." if existed else f"Saved skill '{name}'."
