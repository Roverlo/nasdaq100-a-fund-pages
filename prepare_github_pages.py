import argparse
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE_HTML = ROOT / "纳指基金支付宝对比表.html"
DOCS_DIR = ROOT / "docs"


class PublicPageFilter(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    PRIVATE_ATTRS = {"data-status", "data-holding-amount", "data-auto-invest-amount", "data-paused-auto-invest-amount"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.output: list[str] = []
        self.skip_depth = 0
        self.in_main_table = False
        self.main_table_depth = 0
        self.in_tr = False
        self.cell_index = 0
        self.in_head = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if self.skip_depth:
            self.skip_depth += 1
            return
        if tag == "button" and attrs_dict.get("id") == "tab-portfolio":
            self.output.append('<a class="tab-button tab-link" href="portfolio.html">持仓定投</a>')
            self.skip_depth = 1
            return
        if tag == "section" and attrs_dict.get("id") == "panel-portfolio":
            self.skip_depth = 1
            return
        if tag == "div" and attrs_dict.get("id") == "portfolio-editor":
            self.skip_depth = 1
            return
        if tag == "div" and attrs_dict.get("id") == "status-filter":
            self.skip_depth = 1
            return
        if tag == "table" and attrs_dict.get("id") == "main-table":
            self.in_main_table = True
            self.main_table_depth = 1
        elif self.in_main_table and tag not in self.VOID_TAGS:
            self.main_table_depth += 1
        if self.in_main_table and tag == "colgroup":
            self.cell_index = 0
        if self.in_main_table and tag == "tr":
            self.in_tr = True
            self.cell_index = 0
        if self.in_main_table and tag in {"th", "td", "col"}:
            self.cell_index += 1
            if self.cell_index in {4, 18}:
                if tag == "col":
                    return
                self.skip_depth = 1
                return
        if tag == "head":
            self.in_head = True
        if self.in_main_table:
            attrs = [(name, value) for name, value in attrs if name not in self.PRIVATE_ATTRS]
        self.output.append(self.render_starttag(tag, attrs))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skip_depth:
            return
        self.output.append(self.render_starttag(tag, attrs, close=True))

    def handle_endtag(self, tag: str) -> None:
        if self.skip_depth:
            self.skip_depth -= 1
            return
        if self.in_main_table:
            self.main_table_depth -= 1
            if tag == "tr":
                self.in_tr = False
                self.cell_index = 0
            if self.main_table_depth == 0:
                self.in_main_table = False
        if tag == "head":
            self.output.append(
                """
  <style>
    .tab-link { color: var(--muted); text-decoration: none; }
    .tab-link:hover { color: var(--ink); background: #f4f2ea; }
    #main-table { width: 1958px; min-width: 1958px; }
    #main-table th:nth-child(4), #main-table td:nth-child(4) {
      position: static; left: auto; box-shadow: none; z-index: auto;
    }
    #main-table tbody tr:nth-child(even) td:nth-child(4),
    #main-table tbody tr:nth-child(odd) td:nth-child(4),
    #main-table tbody tr:hover td:nth-child(4) { background: inherit; }
    #main-table th:nth-child(4) { background: #f1efe6; }
  </style>
"""
            )
            self.in_head = False
        self.output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.output.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self.skip_depth:
            self.output.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self.skip_depth:
            self.output.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        if not self.skip_depth:
            self.output.append(f"<!--{data}-->")

    def render_starttag(self, tag: str, attrs: list[tuple[str, str | None]], close: bool = False) -> str:
        attr_text = "".join(
            f' {name}' if value is None else f' {name}="{self.escape_attr(value)}"'
            for name, value in attrs
        )
        closer = " /" if close else ""
        return f"<{tag}{attr_text}{closer}>"

    @staticmethod
    def escape_attr(value: str) -> str:
        return (
            value.replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def get_html(self) -> str:
        return "".join(self.output)


def strip_private_data(html: str) -> str:
    html = re.sub(
        r'\s*<div class="filter-control">\s*<span class="filter-label">定投状态</span>\s*<div class="select-menu" id="status-filter".*?</div>\s*</div>',
        "",
        html,
        count=1,
        flags=re.S,
    )
    parser = PublicPageFilter()
    parser.feed(html)
    public_html = parser.get_html()
    public_html = re.sub(r"const initialPortfolioState = \{.*?\};", "const initialPortfolioState = {};", public_html, flags=re.S)
    public_html = public_html.replace("纳指 100 A 类基金池", "纳指 100 A 类基金池")
    return public_html


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare GitHub Pages public HTML files.")
    parser.parse_args()
    html = SOURCE_HTML.read_text(encoding="utf-8")
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "index.html").write_text(strip_private_data(html), encoding="utf-8")
    shutil.copy2(SOURCE_HTML, DOCS_DIR / "portfolio.html")
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")
    print(f"wrote {DOCS_DIR / 'index.html'}")
    print(f"wrote {DOCS_DIR / 'portfolio.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
