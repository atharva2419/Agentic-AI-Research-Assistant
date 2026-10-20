"""Load prompt files (prompts/*.md) and fill in their placeholders.

File format:

    # <title, ignored>
    ## system
    ...system prompt...
    ## user
    ...user message with {{placeholders}}...

Placeholders use double braces so JSON examples in prompts don't clash with them. Rendering
fails loudly if a placeholder is missing or a value is never used.
"""

import re
from dataclasses import dataclass
from pathlib import Path

PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
SECTION = re.compile(r"^## (system|user)\s*$", re.MULTILINE)


class PromptError(Exception):
    pass


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    system: str
    user: str

    @property
    def placeholders(self) -> set[str]:
        return set(PLACEHOLDER.findall(self.system)) | set(PLACEHOLDER.findall(self.user))

    def render(self, **values: str) -> "RenderedPrompt":
        missing = self.placeholders - values.keys()
        unused = values.keys() - self.placeholders
        if missing or unused:
            raise PromptError(
                f"prompt '{self.name}': missing values {sorted(missing)}, "
                f"unused values {sorted(unused)}"
            )

        def fill(text: str) -> str:
            return PLACEHOLDER.sub(lambda m: values[m.group(1)], text)

        return RenderedPrompt(system=fill(self.system), user=fill(self.user))


@dataclass(frozen=True)
class RenderedPrompt:
    system: str
    user: str


def parse_prompt(name: str, text: str) -> PromptTemplate:
    parts = SECTION.split(text)
    # parts = [preamble, "system", body, "user", body]
    sections = dict(zip(parts[1::2], parts[2::2], strict=True))
    if set(sections) != {"system", "user"}:
        raise PromptError(
            f"prompt '{name}' needs exactly one '## system' and one '## user' section"
        )
    return PromptTemplate(
        name=name, system=sections["system"].strip(), user=sections["user"].strip()
    )


class PromptLibrary:
    """Loads prompt files on first use and caches them."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._cache: dict[str, PromptTemplate] = {}

    def get(self, filename: str) -> PromptTemplate:
        if filename not in self._cache:
            path = self._directory / filename
            if not path.is_file():
                raise PromptError(f"prompt file not found: {path}")
            self._cache[filename] = parse_prompt(filename, path.read_text(encoding="utf-8"))
        return self._cache[filename]
