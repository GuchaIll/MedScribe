"""
PromptRegistry — loads versioned prompt YAMLs from agents/prompts/<id>/v<N>.yaml.

Layout per §19.3:
  - Every prompt is a file: prompts/<prompt_id>/v<N>.yaml
  - code references prompt_id only; new code has no inline prompt strings
  - Any text change is a new version file; old versions stay for replay
  - The active version per role is pinned in config
  - Every LLM span records prompt_id, prompt_version, and sha256 of template
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict, NamedTuple, Optional

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:
    yaml = None  # type: ignore[assignment]

_PROMPTS_DIR = Path(__file__).parent
_VERSION_RE = re.compile(r"^v(\d+)$")

REQUIRED_YAML_KEYS = {"id", "version", "model_role", "template", "input_schema", "output_schema", "changelog"}


class PromptEntry(NamedTuple):
    prompt_id: str
    version: int
    model_role: str
    template: str
    input_schema: Dict
    output_schema: Dict
    changelog: str
    sha256: str


class RegistryError(Exception):
    pass


class PromptRegistry:
    """
    Loads all prompt versions from the prompts/ directory tree on first use.

    Usage::

        registry = PromptRegistry()
        entry = registry.get("slot_extract")      # active version
        entry = registry.get("slot_extract", 1)   # pinned version

    The active version per prompt_id is the highest version number unless
    overridden via `active_versions` at construction time (from config).
    """

    def __init__(
        self,
        prompts_dir: Optional[Path] = None,
        active_versions: Optional[Dict[str, int]] = None,
    ) -> None:
        self._dir = prompts_dir or _PROMPTS_DIR
        self._active_versions: Dict[str, int] = active_versions or {}
        self._entries: Dict[str, Dict[int, PromptEntry]] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        if yaml is None:
            raise RegistryError("PyYAML is required for PromptRegistry; add 'pyyaml' to requirements.txt")
        for prompt_dir in sorted(self._dir.iterdir()):
            if not prompt_dir.is_dir() or prompt_dir.name.startswith("_"):
                continue
            prompt_id = prompt_dir.name
            for yaml_path in sorted(prompt_dir.glob("v*.yaml")):
                match = _VERSION_RE.match(yaml_path.stem)
                if not match:
                    continue
                version_num = int(match.group(1))
                with yaml_path.open("r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh)
                missing = REQUIRED_YAML_KEYS - data.keys()
                if missing:
                    raise RegistryError(
                        f"{yaml_path}: missing required keys: {sorted(missing)}"
                    )
                if data["id"] != prompt_id:
                    raise RegistryError(
                        f"{yaml_path}: id field {data['id']!r} does not match directory name {prompt_id!r}"
                    )
                if data["version"] != version_num:
                    raise RegistryError(
                        f"{yaml_path}: version field {data['version']!r} does not match "
                        f"filename version {version_num}"
                    )
                template: str = data["template"]
                sha = hashlib.sha256(template.encode()).hexdigest()
                entry = PromptEntry(
                    prompt_id=prompt_id,
                    version=version_num,
                    model_role=data["model_role"],
                    template=template,
                    input_schema=data.get("input_schema") or {},
                    output_schema=data.get("output_schema") or {},
                    changelog=data.get("changelog") or "",
                    sha256=sha,
                )
                self._entries.setdefault(prompt_id, {})[version_num] = entry
        self._loaded = True

    def get(self, prompt_id: str, version: Optional[int] = None) -> PromptEntry:
        self._load()
        if prompt_id not in self._entries:
            raise RegistryError(f"unknown prompt_id: {prompt_id!r}")
        versions = self._entries[prompt_id]
        if version is None:
            version = self._active_versions.get(prompt_id, max(versions))
        if version not in versions:
            raise RegistryError(
                f"prompt {prompt_id!r} version {version} not found; available: {sorted(versions)}"
            )
        return versions[version]

    def list_ids(self) -> list[str]:
        self._load()
        return sorted(self._entries)

    def list_versions(self, prompt_id: str) -> list[int]:
        self._load()
        if prompt_id not in self._entries:
            raise RegistryError(f"unknown prompt_id: {prompt_id!r}")
        return sorted(self._entries[prompt_id])
