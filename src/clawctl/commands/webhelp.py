"""clawctl webhelp — local documentation server."""

from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

console = Console()


def _find_docs_dir() -> Path:
    """Locate the docs/ directory relative to the repo root."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "docs"
        if candidate.is_dir() and (candidate / "index.md").exists():
            return candidate
        if (parent / "pyproject.toml").exists():
            return parent / "docs"
    return Path.cwd() / "docs"


CSS = """\
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    color: #1f2328; background: #fff; line-height: 1.6;
    display: flex; min-height: 100vh;
}
nav {
    width: 260px; min-width: 260px; background: #f6f8fa;
    border-right: 1px solid #d1d9e0; padding: 24px 16px;
    position: sticky; top: 0; height: 100vh; overflow-y: auto;
}
nav h2 { font-size: 14px; font-weight: 600; color: #656d76; text-transform: uppercase;
    letter-spacing: 0.5px; margin-bottom: 12px; }
nav a {
    display: block; padding: 6px 10px; margin: 2px 0; border-radius: 6px;
    color: #1f2328; text-decoration: none; font-size: 14px;
}
nav a:hover { background: #ddf4ff; color: #0969da; }
nav a.active { background: #ddf4ff; color: #0969da; font-weight: 600; }
main {
    flex: 1; max-width: 880px; padding: 40px 48px;
}
h1 { font-size: 2em; font-weight: 600; border-bottom: 1px solid #d1d9e0;
    padding-bottom: 0.3em; margin-bottom: 16px; }
h2 { font-size: 1.5em; font-weight: 600; border-bottom: 1px solid #d1d9e0;
    padding-bottom: 0.3em; margin-top: 24px; margin-bottom: 16px; }
h3 { font-size: 1.25em; font-weight: 600; margin-top: 24px; margin-bottom: 16px; }
p { margin-bottom: 16px; }
a { color: #0969da; text-decoration: none; }
a:hover { text-decoration: underline; }
ul, ol { padding-left: 2em; margin-bottom: 16px; }
li { margin-bottom: 4px; }
code {
    background: #eff1f3; padding: 0.2em 0.4em; border-radius: 4px;
    font-family: ui-monospace, "SFMono-Regular", "SF Mono", Menlo, monospace;
    font-size: 85%;
}
pre {
    background: #f6f8fa; border: 1px solid #d1d9e0; border-radius: 6px;
    padding: 16px; overflow-x: auto; margin-bottom: 16px;
}
pre code { background: none; padding: 0; font-size: 85%; }
table { border-collapse: collapse; margin-bottom: 16px; width: 100%; }
th, td { border: 1px solid #d1d9e0; padding: 8px 12px; text-align: left; }
th { background: #f6f8fa; font-weight: 600; }
blockquote {
    border-left: 4px solid #d1d9e0; padding: 0 16px; color: #656d76;
    margin-bottom: 16px;
}
input[type="checkbox"] { margin-right: 6px; }
"""


def _build_nav(docs_dir: Path, active: str = "") -> str:
    """Build the sidebar navigation HTML from docs/ files."""
    links: list[str] = []
    for md in sorted(docs_dir.glob("*.md")):
        if md.name == "index.md":
            continue
        name = md.stem
        title = name.replace("-", " ").title()
        # Read the first H1 from the file for a better title
        try:
            for line in md.read_text().splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
        except OSError:
            pass
        cls = ' class="active"' if name == active else ""
        links.append(f'<a href="/doc/{name}"{cls}>{title}</a>')
    return "\n".join(links)


def _render_page(docs_dir: Path, title: str, html_content: str, active: str = "") -> str:
    """Wrap rendered markdown in the full HTML page template."""
    nav = _build_nav(docs_dir, active)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — OpenClaw Docs</title>
<style>{CSS}</style>
</head>
<body>
<nav>
<h2>OpenClaw Docs</h2>
<a href="/"{"  class=\"active\"" if active == "index" else ""}>Home</a>
{nav}
</nav>
<main>
{html_content}
</main>
</body>
</html>"""


def _create_app(docs_dir: Path):
    """Create and return the FastAPI application."""
    import markdown
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse

    app = FastAPI(title="OpenClaw Docs")
    md = markdown.Markdown(extensions=["fenced_code", "tables", "toc", "sane_lists"])

    @app.get("/", response_class=HTMLResponse)
    async def index():
        index_file = docs_dir / "index.md"
        if index_file.exists():
            md.reset()
            content = md.convert(index_file.read_text())
            # Rewrite relative .md links to /doc/ routes
            content = _rewrite_links(content)
        else:
            content = "<h1>Documentation</h1><p>No index.md found.</p>"
        return _render_page(docs_dir, "Home", content, active="index")

    @app.get("/doc/{name}", response_class=HTMLResponse)
    async def doc(name: str):
        md_file = docs_dir / f"{name}.md"
        if not md_file.exists() or not md_file.is_relative_to(docs_dir):
            return HTMLResponse(
                _render_page(docs_dir, "Not Found", "<h1>Not Found</h1>"),
                status_code=404,
            )
        md.reset()
        content = md.convert(md_file.read_text())
        content = _rewrite_links(content)
        title = name.replace("-", " ").title()
        for line in md_file.read_text().splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        return _render_page(docs_dir, title, content, active=name)

    return app


def _rewrite_links(html: str) -> str:
    """Rewrite href="foo.md" links to href="/doc/foo" for in-app navigation."""
    import re
    return re.sub(
        r'href="([^":/]+)\.md"',
        lambda m: f'href="/doc/{m.group(1)}"',
        html,
    )


def webhelp(
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="Port to serve on"),
    ] = 8070,
    no_open: Annotated[
        bool,
        typer.Option("--no-open", help="Don't auto-open the browser"),
    ] = False,
) -> None:
    """Browse project documentation in your browser."""
    import uvicorn

    docs_dir = _find_docs_dir()
    if not docs_dir.exists():
        console.print(f"[red]Docs directory not found at {docs_dir}[/red]")
        raise typer.Exit(1)

    app = _create_app(docs_dir)
    url = f"http://localhost:{port}"
    console.print(f"Serving docs from [bold]{docs_dir}[/bold]")
    console.print(f"Open [link={url}]{url}[/link] (Ctrl+C to stop)\n")

    if not no_open:
        webbrowser.open(url)

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
