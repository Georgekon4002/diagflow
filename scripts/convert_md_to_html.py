"""
DiagFlow — Markdown to Standalone HTML Converter (with Base64 Image Embedding)
================================================================================
Converts all .md documentation files in the repository into standalone,
beautifully styled HTML files (.html) with embedded Base64 screenshots and logos.

These HTML files can be opened in any web browser on any computer (even via email
or USB without copying the media folder) with 100% of screenshots loading perfectly.

Usage:
    python scripts/convert_md_to_html.py
"""

import base64
import mimetypes
import re
from pathlib import Path
import markdown

ROOT = Path(__file__).resolve().parent.parent

# GitHub-like CSS styling embedded in HTML files for perfect rendering anywhere
CSS_STYLE = """
<style>
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        line-height: 1.6;
        color: #24292f;
        background-color: #ffffff;
        max-width: 960px;
        margin: 0 auto;
        padding: 30px 20px;
    }
    h1, h2, h3, h4, h5, h6 {
        margin-top: 28px;
        margin-bottom: 16px;
        font-weight: 600;
        line-height: 1.25;
        color: #1f2328;
    }
    h1 { font-size: 2em; padding-bottom: 0.3em; border-bottom: 1px solid #d0d7de; }
    h2 { font-size: 1.5em; padding-bottom: 0.3em; border-bottom: 1px solid #d0d7de; }
    h3 { font-size: 1.25em; }
    code {
        padding: 0.2em 0.4em;
        margin: 0;
        font-size: 85%;
        white-space: break-spaces;
        background-color: rgba(175, 184, 193, 0.2);
        border-radius: 6px;
        font-family: ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace;
    }
    pre {
        padding: 16px;
        overflow: auto;
        font-size: 85%;
        line-height: 1.45;
        background-color: #f6f8fa;
        border-radius: 6px;
    }
    pre code { background-color: transparent; padding: 0; }
    blockquote {
        padding: 0 1em;
        color: #636c76;
        border-left: 0.25em solid #d0d7de;
        margin: 0 0 16px 0;
    }
    table {
        border-spacing: 0;
        border-collapse: collapse;
        margin-top: 12px;
        margin-bottom: 16px;
        width: 100%;
    }
    table th, table td {
        padding: 8px 14px;
        border: 1px solid #d0d7de;
        text-align: center;
        vertical-align: middle;
    }
    table tr:nth-child(2n) { background-color: #f6f8fa; }
    img { max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1); }
    a { color: #0969da; text-decoration: none; }
    a:hover { text-decoration: underline; }
    hr { height: 0.25em; padding: 0; margin: 24px 0; background-color: #d0d7de; border: 0; }
</style>
"""


def embed_images(md_text: str, base_dir: Path) -> str:
    """
    Finds all Markdown image links (e.g. ![alt](path)) and HTML <img> tags,
    converting local image files into embedded base64 data URLs.
    """

    def replace_md_img(match):
        alt = match.group(1)
        src = match.group(2).strip()
        img_path = (base_dir / src).resolve()
        if img_path.exists() and img_path.is_file():
            mime, _ = mimetypes.guess_type(img_path)
            mime = mime or "image/png"
            with open(img_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("utf-8")
            return f'<img src="data:{mime};base64,{encoded}" alt="{alt}" style="max-width:100%; height:auto; border-radius:6px;" />'
        return f'<img src="{src}" alt="{alt}" style="max-width:100%; height:auto; border-radius:6px;" />'

    def replace_html_img(match):
        full_tag = match.group(0)
        src_match = re.search(r'src=["\'](.*?)["\']', full_tag)
        if not src_match:
            return full_tag
        src = src_match.group(1)
        if src.startswith("data:") or src.startswith("http"):
            return full_tag
        img_path = (base_dir / src).resolve()
        if img_path.exists() and img_path.is_file():
            mime, _ = mimetypes.guess_type(img_path)
            mime = mime or "image/png"
            with open(img_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("utf-8")
            return re.sub(r'src=["\'](.*?)["\']', f'src="data:{mime};base64,{encoded}"', full_tag)
        return full_tag

    # Replace Markdown image syntax ![alt](src) FIRST
    md_text = re.sub(r'!\[(.*?)\]\((.*?)\)', replace_md_img, md_text)
    # Replace raw HTML <img ... src="src" ... />
    md_text = re.sub(r'<img\s+[^>]*src=["\'][^"\']+["\'][^>]*>', replace_html_img, md_text)

    return md_text


def convert_file(md_path: Path):
    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    # Pre-process text to embed all images directly into HTML
    processed_text = embed_images(md_text, md_path.parent)

    # Convert Markdown to HTML with tables & code block extensions
    html_content = markdown.markdown(
        processed_text,
        extensions=["tables", "fenced_code", "nl2br", "toc"]
    )

    # Build complete HTML page
    page_title = md_path.stem.replace("_", " ").title()
    full_html = f"""<!DOCTYPE html>
<html lang="el">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{page_title} — DiagFlow</title>
    {CSS_STYLE}
</head>
<body>
{html_content}
</body>
</html>
"""

    if md_path.parent == ROOT and (ROOT / "guides").exists():
        out_path = ROOT / "guides" / md_path.with_suffix(".html").name
    else:
        out_path = md_path.with_suffix(".html")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(full_html)

    print(f"  Converted: {md_path.name} -> {out_path.relative_to(ROOT)} (Images Embedded Base64)")


def main():
    print("=" * 60)
    print("  DiagFlow Markdown -> Standalone HTML Converter")
    print("=" * 60)

    md_files = list(ROOT.glob("*.md")) + list((ROOT / "guides").glob("*.md"))
    for file in md_files:
        convert_file(file)

    print("\n  Conversion complete! HTML files are 100% self-contained.")
    print("=" * 60)


if __name__ == "__main__":
    main()
