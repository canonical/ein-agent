"""Load agent prompt templates from external markdown files."""

from pathlib import Path
from string import Template

_PROMPTS_DIR = Path(__file__).resolve().parents[3] / 'prompts' / 'agents'


def load_template(name: str) -> Template:
    """Load a prompt template by agent name.

    Args:
        name: Template filename without extension (e.g. 'planning_agent')

    Returns:
        A string.Template ready for .substitute() calls.
    """
    path = _PROMPTS_DIR / f'{name}.md'
    return Template(path.read_text())
