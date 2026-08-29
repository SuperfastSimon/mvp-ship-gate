#!/usr/bin/env python3
"""MVP Ship Gate automatic validators. Stdlib only."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

SKIP_DIRS = {
    ".git", "node_modules", ".next", "dist", "build", "coverage", "vendor",
    "__pycache__", ".venv", "venv", ".grok", ".turbo", ".cache",
}
CODE_SUFFIX = {
    ".html", ".htm", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte",
    ".mdx", ".astro", ".css", ".scss", ".md", ".py", ".php", ".rb",
}
WEB_SUFFIX = {".html", ".htm", ".jsx", ".tsx", ".vue", ".svelte", ".mdx", ".astro"}
FORM_HINTS = re.compile(
    r"<form\b|type=[\"']email[\"']|type=[\"']password[\"']|next-auth|clerk\(|@supabase/auth|stripe\(|newsletter|mailchimp|inputMode=[\"']email[\"']",
    re.I,
)
ANALYTICS_HINTS = re.compile(
    r"gtag\(|googletagmanager|plausible\(|umami|segment\.com|mixpanel|posthog|hotjar|facebook\.net/en_US/fbevents",
    re.I,
)
COOKIE_BANNER_HINTS = re.compile(
    r"cookie[-_ ]?banner|CookieBanner|cookiebot|onetrust|cookieconsent|we use cookies to|wij gebruiken cookies",
    re.I,
)

@dataclass
class Finding:
    check: str
    severity: str
    path: str
    line: int
    message: str

def iter_files(root: Path):
    root = root.resolve()
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if p.suffix.lower() not in CODE_SUFFIX and p.name not in {
            "robots.txt", "sitemap.xml", "favicon.ico", ".env", ".env.local", ".env.production",
        }:
            continue
        yield p

def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""

def is_web_project(root: Path, files: list[Path]) -> bool:
    names = {p.name.lower() for p in files}
    if any(n.endswith(".html") or n.endswith(".htm") for n in names):
        return True
    pkg = root / "package.json"
    if pkg.is_file():
        txt = read_text(pkg).lower()
        if any(k in txt for k in ("next", "react", "vite", "astro", "nuxt", "svelte")):
            return True
    return any(p.suffix.lower() in {".tsx", ".jsx", ".vue", ".astro"} for p in files)

def has_pii_signals(files: list[Path]) -> bool:
    return any(FORM_HINTS.search(read_text(p)) for p in files)

def exists_any(root: Path, rels: list[str]) -> bool:
    return any((root / r).is_file() for r in rels)

def line_hits(path: Path, pattern: re.Pattern) -> list[tuple[int, str]]:
    out = []
    for i, line in enumerate(read_text(path).splitlines(), 1):
        if pattern.search(line):
            out.append((i, line.strip()[:160]))
    return out

def check_docs(root: Path, findings: list[Finding], pii: bool) -> None:
    if not exists_any(root, ["README.md", "docs/README.md"]):
        findings.append(Finding("docs.readme", "FAIL", str(root), 0, "README.md missing"))
    if not exists_any(root, ["TERMS.md", "docs/TERMS.md", "VOORWAARDEN.md", "docs/VOORWAARDEN.md"]):
        findings.append(Finding("docs.terms", "FAIL", str(root), 0, "TERMS.md / VOORWAARDEN.md missing"))
    ux = exists_any(root, ["UX_NOTES.md", "docs/UX_NOTES.md"])
    readme = root / "README.md"
    if not ux and readme.is_file() and re.search(r"^#+\s+(ux|design)\b", read_text(readme), re.I | re.M):
        ux = True
    if not ux:
        findings.append(Finding("docs.ux_notes", "FAIL", str(root), 0, "UX_NOTES.md missing and README has no Design/UX heading"))
    privacy = exists_any(root, ["PRIVACY.md", "docs/PRIVACY.md", "PRIVACYBELEID.md", "docs/PRIVACYBELEID.md"])
    if pii and not privacy:
        findings.append(Finding("docs.privacy_if_pii", "FAIL", str(root), 0, "Personal-data signals found but PRIVACY.md is missing (pin 2A)"))
    if privacy and not pii:
        findings.append(Finding("docs.privacy_if_pii", "INFO", str(root), 0, "PRIVACY.md present without form/auth/analytics hints — ok, not required"))

def check_patterns(files: list[Path], findings: list[Finding]) -> None:
    rules = [
        ("copy.lorem", re.compile(r"lorem ipsum|dolor sit amet|consectetur adipiscing", re.I), "placeholder copy"),
        ("copy.todo", re.compile(r"\b(TODO|FIXME|XXX|HACK)\b"), "todo marker"),
        ("copy.coming_soon", re.compile(r"coming soon|binnenkort beschikbaar|\bTBD\b|under construction", re.I), "coming-soon copy"),
        ("ui.dead_href", re.compile(r"""href\s*=\s*[\"']#[\"']|href\s*=\s*[\"'][\"']|javascript:void\(0\)"""), "dead href"),
        ("ui.empty_handler", re.compile(r"onClick=\{\(\)\s*=>\s*\{\s*\}|onClick=\{\(\)\s*=>\s*undefined\}|@click=\"\s*\"|onclick=\"\s*\""), "empty handler"),
        ("copy.dummy_identity", re.compile(r"john doe|jane doe|test@test\.com|youremail@|naam@bedrijf\.nl", re.I), "dummy identity"),
    ]
    for path in files:
        text = read_text(path)
        if not text:
            continue
        rel = str(path)
        if "mvp-ship-gate" in rel and path.name in {"anti-patterns.md", "definition-of-done.md", "SKILL.md", "preflight-scan.sh", "mvp_validate.py"}:
            continue
        for check, pat, msg in rules:
            for lineno, snippet in line_hits(path, pat):
                findings.append(Finding(check, "FAIL", str(path), lineno, f"{msg}: {snippet}"))

def check_secrets(files: list[Path], findings: list[Finding]) -> None:
    env_pat = re.compile(r"^(?!#).*(SECRET|API_KEY|PRIVATE_KEY|TOKEN)\s*=\s*\S+", re.I)
    key_pat = re.compile(r"BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY")
    assigned = re.compile(r"""api[_-]?key\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}""", re.I)
    for path in files:
        name = path.name
        if name.startswith(".env") and name not in {".env.example", ".env.sample"}:
            findings.append(Finding("secrets.env_file", "FAIL", str(path), 0, "env file other than .env.example should not be committed"))
        for i, line in enumerate(read_text(path).splitlines(), 1):
            if key_pat.search(line) or assigned.search(line) or (
                name.startswith(".env") and env_pat.search(line) and "EXAMPLE" not in line.upper()
                and "CHANGE_ME" not in line.upper() and "your-" not in line.lower()
            ):
                if name == ".env.example" or path.suffix == ".md":
                    continue
                findings.append(Finding("secrets.committed", "FAIL", str(path), i, line.strip()[:160]))

def check_images_alt(files: list[Path], findings: list[Finding]) -> None:
    img = re.compile(r"<img\b[^>]*>", re.I)
    has_alt = re.compile(r"\balt\s*=", re.I)
    jsx_img = re.compile(r"<Image\b[^>]*>", re.I)
    for path in files:
        if path.suffix.lower() not in WEB_SUFFIX | {".html", ".htm", ".mdx"}:
            continue
        for i, line in enumerate(read_text(path).splitlines(), 1):
            for tag in img.findall(line) + jsx_img.findall(line):
                if not has_alt.search(tag):
                    findings.append(Finding("a11y.img_alt", "FAIL", str(path), i, "img/Image without alt"))

def check_cookie_pin2(files: list[Path], findings: list[Finding]) -> None:
    texts = [read_text(p) for p in files]
    if any(COOKIE_BANNER_HINTS.search(t) for t in texts) and not any(ANALYTICS_HINTS.search(t) for t in texts):
        findings.append(Finding(
            "privacy.cookie_banner_without_trackers", "FAIL",
            str(files[0].parent if files else "."), 0,
            "Cookie banner/consent copy found without analytics/tracker signals (pin 2A)",
        ))

def check_web_chrome(root: Path, files: list[Path], findings: list[Finding], mode: str) -> None:
    if mode != "full":
        return
    robots = [p for p in list(root.rglob("robots.txt")) + list(root.rglob("robots.ts")) + list(root.rglob("robots.js")) if not any(part in SKIP_DIRS for part in p.relative_to(root).parts)]
    if not robots:
        findings.append(Finding("seo.robots", "FAIL", str(root), 0, "no robots.txt/ts for public web project"))
    fav = []
    for name in ("favicon.ico", "favicon.svg", "favicon.png", "icon.png", "icon.svg", "icon.tsx"):
        fav.extend(root.rglob(name))
    fav = [p for p in fav if not any(part in SKIP_DIRS for part in p.relative_to(root).parts)]
    if not fav:
        findings.append(Finding("seo.favicon", "FAIL", str(root), 0, "no favicon/icon for public web project"))
    sm = [p for p in list(root.rglob("sitemap.xml")) + list(root.rglob("sitemap.ts")) if not any(part in SKIP_DIRS for part in p.relative_to(root).parts)]
    if not sm:
        findings.append(Finding("seo.sitemap", "INFO", str(root), 0, "no sitemap.xml/ts found"))
    lang = title = desc = og = False
    for path in files:
        if path.suffix.lower() not in WEB_SUFFIX | {".html", ".htm", ".ts", ".js"}:
            continue
        txt = read_text(path)
        if re.search(r"<html[^>]*lang\s*=", txt, re.I) or re.search(r"""lang:\s*['\"]""", txt):
            lang = True
        if re.search(r"<title\b|metadata\s*\([^)]*title", txt, re.I) or re.search(r"title:\s*['\"]", txt):
            title = True
        if re.search(r"name=[\"']description[\"']|description:\s*['\"]", txt, re.I):
            desc = True
        if re.search(r"og:image|openGraph", txt, re.I):
            og = True
    if not lang:
        findings.append(Finding("seo.lang", "FAIL", str(root), 0, "no html lang / lang field found"))
    if not title:
        findings.append(Finding("seo.title", "FAIL", str(root), 0, "no title found"))
    if not desc:
        findings.append(Finding("seo.description", "FAIL", str(root), 0, "no meta description found"))
    if not og:
        findings.append(Finding("seo.og_image", "INFO", str(root), 0, "no og:image / openGraph found"))

def check_internal_routes(root: Path, files: list[Path], findings: list[Finding]) -> None:
    page_routes = set()
    for p in files:
        rel = p.relative_to(root).as_posix()
        if "/app/" in f"/{rel}" and p.name in {"page.tsx", "page.ts", "page.jsx", "page.js", "page.mdx"}:
            parent = p.parent.relative_to(root).as_posix()
            idx = parent.find("/app/")
            route = parent[idx + 4 :] if idx >= 0 else ("" if parent.endswith("/app") else parent.split("/app/")[-1])
            route = "/" + re.sub(r"\(.*?\)/", "", route + "/").replace("/page", "")
            route = re.sub(r"/+", "/", route).rstrip("/") or "/"
            route = re.sub(r"/\([^/]+\)", "", route) or "/"
            page_routes.add(route)
        if p.suffix.lower() in {".html", ".htm"}:
            name = p.stem if p.stem != "index" else ""
            route = "/" + name if name else "/"
            page_routes.add(route)
            if name:
                page_routes.add(route + p.suffix.lower())
    href_re = re.compile(r"""href\s*=\s*[\"'](/[A-Za-z0-9_/\-.]*)[\"']""")
    if not page_routes:
        return
    for path in files:
        if path.suffix.lower() not in WEB_SUFFIX | {".html", ".htm", ".ts", ".js", ".mdx"}:
            continue
        for i, line in enumerate(read_text(path).splitlines(), 1):
            for m in href_re.finditer(line):
                dest = m.group(1).split("#")[0].split("?")[0]
                if dest.startswith("/http") or dest.startswith("//") or dest.startswith("/api/") or "[" in dest:
                    continue
                dest_norm = re.sub(r"\.(html?)$", "", dest.rstrip("/")) or "/"
                if dest in page_routes or dest.rstrip("/") in page_routes or dest_norm in page_routes:
                    continue
                if (root / "public" / dest.lstrip("/")).exists() or (root / dest.lstrip("/")).exists():
                    continue
                findings.append(Finding("routes.missing_internal", "FAIL", str(path), i, f"internal href {dest} has no matching page/html"))

def summarize(findings: list[Finding]) -> dict:
    fails = [f for f in findings if f.severity == "FAIL"]
    infos = [f for f in findings if f.severity == "INFO"]
    by = {}
    for f in findings:
        by.setdefault(f.check, {"FAIL": 0, "INFO": 0})
        by[f.check][f.severity] += 1
    return {"fail_count": len(fails), "info_count": len(infos), "by_check": by, "result": "FAIL" if fails else "PASS"}

def relpath(root: Path, path: str) -> str:
    try:
        return str(Path(path).resolve().relative_to(root))
    except ValueError:
        return path

def emit_github(root: Path, findings: list[Finding]) -> None:
    for f in findings:
        rp = relpath(root, f.path)
        line = f.line if f.line > 0 else 1
        kind = "error" if f.severity == "FAIL" else "notice"
        msg = f"{f.check}: {f.message}".replace("\n", " ")
        print(f"::{kind} file={rp},line={line}::{msg}")

def emit_junit(root: Path, findings: list[Finding], summary: dict) -> str:
    from xml.sax.saxutils import escape
    fails = [f for f in findings if f.severity == "FAIL"]
    cases = []
    if not fails:
        cases.append('    <testcase classname="mvp-ship-gate" name="all-checks" />')
    for f in fails:
        rp = escape(relpath(root, f.path))
        name = escape(f"{f.check} {rp}:{f.line}")
        msg = escape(f.message)
        cases.append(f'    <testcase classname="{escape(f.check)}" name="{name}">\n      <failure message="{msg}">{rp}:{f.line} {msg}</failure>\n    </testcase>')
    body = "\n".join(cases)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<testsuite name="mvp-ship-gate" tests="{max(len(fails), 1)}" failures="{len(fails)}" skipped="0">\n{body}\n</testsuite>\n'

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--mode", choices=("light", "full"), default="full")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--format", choices=("text", "json", "github", "junit"), default="text")
    ap.add_argument("--report", default="")
    args = ap.parse_args()
    if args.json:
        args.format = "json"
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"FAIL: not a directory: {root}", file=sys.stderr)
        return 2
    files = list(iter_files(root))
    web = is_web_project(root, files)
    pii = has_pii_signals(files)
    findings: list[Finding] = []
    check_docs(root, findings, pii)
    check_patterns(files, findings)
    check_secrets(files, findings)
    check_images_alt(files, findings)
    check_cookie_pin2(files, findings)
    if web:
        check_web_chrome(root, files, findings, args.mode)
        check_internal_routes(root, files, findings)
    summary = summarize(findings)
    payload = {
        "root": str(root), "mode": args.mode, "web_project": web, "pii_signals": pii,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": summary, "findings": [asdict(f) for f in findings],
    }
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if args.format == "json":
        print(json.dumps(payload, indent=2))
    elif args.format == "github":
        emit_github(root, findings)
        print(f"::notice::mvp-ship-gate {summary['result']} fail={summary['fail_count']} info={summary['info_count']}")
    elif args.format == "junit":
        print(emit_junit(root, findings, summary), end="")
    else:
        print("MVP ship-gate automatic validation")
        print(f"root: {root}\nmode: {args.mode}\nweb_project: {web}\npii_signals: {pii}\ngenerated_at: {payload['generated_at']}\n")
        current = None
        if not findings:
            print("(no findings)")
        for f in findings:
            if f.check != current:
                current = f.check
                print(f"== {f.check} ==")
            loc = f.path if f.line == 0 else f"{f.path}:{f.line}"
            print(f"{f.severity:4} {loc}  {f.message}\n")
        print(f"== summary ==\nfail_count: {summary['fail_count']}\ninfo_count: {summary['info_count']}\nRESULT: {summary['result']}")
    return 1 if summary["result"] == "FAIL" else 0

if __name__ == "__main__":
    sys.exit(main())
