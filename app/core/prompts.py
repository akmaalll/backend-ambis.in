"""Loader for the versioned prompt suite in `prompts/` (architecture §7.1-B).

Resolved relative to this file's location (not the process CWD) so it works
the same whether the app is run via `uvicorn app.main:app`, pytest, or a
one-off Docker script from any working directory.
"""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"
_env = Environment(loader=FileSystemLoader(str(_PROMPTS_DIR)))


def render_prompt(name: str, **kwargs) -> str:
    """Render prompts/{name}.j2 with the given template variables."""
    template = _env.get_template(f"{name}.j2")
    return template.render(**kwargs)
