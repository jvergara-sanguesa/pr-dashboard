#!/usr/bin/env python3
"""Fetch your open PRs via gh and render the PR dashboard HTML.

Targets whoever is authenticated in `gh` (uses --author=@me). Optionally filters
by a GitHub org via the ORG setting (env var PR_DASHBOARD_ORG or settings.py).
Writes dashboard.html next to this script and prints its path on success.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"
OUTPUT = HERE / "dashboard.html"


def _load_org() -> str:
    """Org to filter PRs by. Env var PR_DASHBOARD_ORG > settings.ORG > none."""
    env = os.environ.get("PR_DASHBOARD_ORG")
    if env is not None:
        return env.strip()
    try:
        import settings  # optional, gitignored local config
        return str(getattr(settings, "ORG", "")).strip()
    except ImportError:
        return ""


ORG = _load_org()

_T0 = time.perf_counter()
_TIMERS: dict[str, float] = {}
_COUNTS: dict[str, int] = {}
LOG_LINES: list[str] = []  # checkpoint lines of the current build (read by server)


def log(msg: str) -> None:
    """Print a checkpoint line prefixed with elapsed time since build start."""
    line = f"[{time.perf_counter() - _T0:6.1f}s] {msg}"
    LOG_LINES.append(line)
    print(line, flush=True)


def _rec(key: str, seconds: float) -> None:
    """Accumulate elapsed time and call count for a labeled step."""
    _TIMERS[key] = _TIMERS.get(key, 0.0) + seconds
    _COUNTS[key] = _COUNTS.get(key, 0) + 1

SEARCH_FIELDS = "number,title,repository,url,createdAt,updatedAt,isDraft,labels"
VIEW_FIELDS = (
    "number,title,url,isDraft,createdAt,updatedAt,additions,deletions,"
    "changedFiles,reviewDecision,mergeable,mergeStateStatus,baseRefName,"
    "headRefName,labels,comments,reviews,statusCheckRollup"
)

PR_QUERY = """
query($owner:String!, $name:String!, $number:Int!) {
  repository(owner:$owner, name:$name) {
    pullRequest(number:$number) {
      reviewThreads(first:100) {
        nodes {
          isResolved
          isOutdated
          path
          line
          comments(first:1) { nodes { author { login } body url createdAt } }
        }
      }
      suggestedReviewers { isAuthor isCommenter reviewer { login } }
    }
  }
}
"""

MAX_THREAD_ITEMS = 12
TOP_CONTRIBUTORS = 6
BODY_MAX = 4000


def clean_body(body: str) -> str:
    """Strip HTML comments and collapse blank lines from a comment body."""
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body[:BODY_MAX]

AUTHOR_LOGIN = ""  # set in main(); excluded from reviewer suggestions
_CONTRIB_CACHE: dict[str, list] = {}


def summarize_thread(body: str) -> tuple[str | None, str]:
    """Return (severity, short_title) parsed from a review-comment body."""
    low = body.lower()
    severity = None
    for keyword, value in (("high severity", "high"),
                           ("medium severity", "medium"),
                           ("low severity", "low")):
        if keyword in low:
            severity = value
            break
    if severity is None:
        if "🔴" in body:
            severity = "high"
        elif "🟠" in body or "🟡" in body:
            severity = "medium"
    title = ""
    for raw in body.splitlines():
        line = raw.strip().lstrip("#").strip()
        if line and not line.startswith("<") and "severity" not in line.lower():
            title = line
            break
    if not title:
        title = body.strip()
    title = re.sub(r"[*_`]", "", title).strip()
    return severity, title[:100]


def fetch_pr_details(owner: str, name: str, number: int) -> dict:
    """Return unresolved review threads and GitHub-suggested reviewers (users)."""
    empty = {"threads": {"unresolved": 0, "items": []}, "suggested": []}
    _t = time.perf_counter()
    res = subprocess.run(
        ["gh", "api", "graphql",
         "-f", f"query={PR_QUERY}",
         "-F", f"owner={owner}", "-F", f"name={name}", "-F", f"number={number}"],
        capture_output=True, text=True,
    )
    _rec("gh api graphql (threads+reviewers)", time.perf_counter() - _t)
    if res.returncode != 0:
        return empty
    try:
        pr = json.loads(res.stdout)["data"]["repository"]["pullRequest"]
        nodes = pr["reviewThreads"]["nodes"]
    except (KeyError, TypeError, json.JSONDecodeError):
        return empty

    items = []
    for thread in nodes:
        if thread.get("isResolved"):
            continue
        comments = (thread.get("comments") or {}).get("nodes") or []
        first = comments[0] if comments else {}
        body = first.get("body", "")
        author = ((first.get("author") or {}).get("login")) or "?"
        severity, title = summarize_thread(body)
        items.append({
            "author": author,
            "path": thread.get("path"),
            "line": thread.get("line"),
            "outdated": bool(thread.get("isOutdated")),
            "severity": severity,
            "title": title,
            "body": clean_body(body),
            "url": first.get("url", ""),
        })
    order = {"high": 0, "medium": 1, "low": 2, None: 3}
    items.sort(key=lambda i: order.get(i["severity"], 3))

    suggested = []
    for sr in (pr.get("suggestedReviewers") or []):
        login = ((sr.get("reviewer") or {}).get("login"))
        if login and login != AUTHOR_LOGIN and login not in suggested:
            suggested.append(login)

    return {
        "threads": {"unresolved": len(items), "items": items[:MAX_THREAD_ITEMS]},
        "suggested": suggested,
    }


def fetch_contributors(owner: str, name: str) -> list:
    """Return up to 6 top human contributors of a repo, ordered by commits."""
    key = f"{owner}/{name}"
    if key in _CONTRIB_CACHE:
        return _CONTRIB_CACHE[key]
    _t = time.perf_counter()
    res = subprocess.run(
        ["gh", "api", f"repos/{owner}/{name}/contributors?per_page=15"],
        capture_output=True, text=True,
    )
    _rec("gh api contributors", time.perf_counter() - _t)
    contributors = []
    if res.returncode == 0:
        try:
            for c in json.loads(res.stdout):
                login = c.get("login", "")
                if (c.get("type") == "User" and not login.endswith("[bot]")
                        and login != AUTHOR_LOGIN):
                    contributors.append({
                        "login": login,
                        "contributions": c.get("contributions", 0),
                    })
                if len(contributors) >= TOP_CONTRIBUTORS:
                    break
        except json.JSONDecodeError:
            pass
    _CONTRIB_CACHE[key] = contributors
    return contributors


# Solo los fallos en estas categorías marcan una PR como "CI en rojo".
# El resto (sonar, datadog, bots de review) se ignora para el estado rojo.
IMPORTANT_CHECK_CATEGORIES = ("ci", "pytest", "docs")


def categorize_check(name: str) -> str:
    """Map a check name to ci/pytest/docs/other ('other' = ruido ignorado)."""
    n = name.lower()
    if "pytest" in n:
        return "pytest"
    if n.startswith("docs") or "docs-check" in n or "check-agent-docs" in n:
        return "docs"
    if (n.startswith("linters") or "build base image" in n
            or "check-service-catalog" in n or "check-toku-lib-imports" in n
            or "repo configuration" in n):
        return "ci"
    return "other"


def summarize_checks(checks: list) -> dict:
    """Count checks and flag which IMPORTANT categories are failing."""
    fail_concl = {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
    total = pending = success = fail = 0
    fail_cats: set[str] = set()
    fail_names: list[str] = []
    for c in checks:
        name = c.get("name") or c.get("context") or ""
        concl = c.get("conclusion") or ""
        state = c.get("state") or ""
        status = c.get("status") or ""
        is_fail = concl in fail_concl or state in {"FAILURE", "ERROR"}
        total += 1
        fail += int(is_fail)
        pending += int((status not in ("", "COMPLETED")) or state == "PENDING")
        success += int(concl == "SUCCESS" or state == "SUCCESS")
        if is_fail:
            cat = categorize_check(name)
            if cat in IMPORTANT_CHECK_CATEGORIES:
                fail_cats.add(cat)
                if name not in fail_names:
                    fail_names.append(name)
    order = {c: i for i, c in enumerate(IMPORTANT_CHECK_CATEGORIES)}
    return {
        "total": total, "fail": fail, "pending": pending, "success": success,
        "failCats": sorted(fail_cats, key=lambda c: order.get(c, 9)),
        "failNames": fail_names[:10],
    }


def run(cmd: list[str]) -> str:
    """Run a command and return stdout, raising with stderr on failure."""
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}\n{res.stderr.strip()}")
    return res.stdout


def fetch_open_prs() -> list[dict]:
    """Return the list of open PRs authored by the current gh user."""
    cmd = ["gh", "search", "prs", "--author=@me", "--state=open",
           "--limit", "100", "--json", SEARCH_FIELDS]
    if ORG:
        cmd += ["--owner", ORG]
    return json.loads(run(cmd))


def enrich(url: str) -> dict | None:
    """Fetch per-PR detail (reviews, CI) for a single PR url."""
    repo = re.sub(r"https://github.com/([^/]+/[^/]+)/pull/.*", r"\1", url)
    _t = time.perf_counter()
    res = subprocess.run(
        ["gh", "pr", "view", url, "--json", VIEW_FIELDS],
        capture_output=True, text=True,
    )
    _rec("gh pr view", time.perf_counter() - _t)
    if res.returncode != 0:
        return None
    pr = json.loads(res.stdout)
    checks = pr.get("statusCheckRollup") or []
    owner, _, name = repo.partition("/")
    details = fetch_pr_details(owner, name, pr["number"])
    threads = details["threads"]
    reviewers = None
    if pr.get("reviewDecision") != "APPROVED":
        reviewers = {
            "contributors": fetch_contributors(owner, name),
            "suggested": details["suggested"],
        }
    return {
        "number": pr["number"],
        "title": pr["title"],
        "url": pr["url"],
        "isDraft": pr["isDraft"],
        "createdAt": pr["createdAt"],
        "updatedAt": pr["updatedAt"],
        "additions": pr["additions"],
        "deletions": pr["deletions"],
        "changedFiles": pr["changedFiles"],
        "reviewDecision": pr.get("reviewDecision", ""),
        "mergeable": pr.get("mergeable", "UNKNOWN"),
        "mergeState": pr.get("mergeStateStatus", "UNKNOWN"),
        "base": pr["baseRefName"],
        "head": pr["headRefName"],
        "repo": re.sub(rf"^{re.escape(ORG)}/", "", repo) if ORG else repo,
        "labels": [lbl["name"] for lbl in pr.get("labels", [])],
        "comments": len(pr.get("comments") or []),
        "reviews": len(pr.get("reviews") or []),
        "threads": threads,
        "reviewers": reviewers,
        "ci": summarize_checks(checks),
    }


def within_work_hours() -> bool:
    """True on Mon-Fri between 09:00 and 18:30 (system local time)."""
    now = datetime.now()
    if now.weekday() > 4:  # 5=Sat, 6=Sun
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 <= minutes <= 18 * 60 + 30


def build_dashboard() -> dict:
    """Fetch data from GitHub and write the dashboard HTML atomically.

    Returns run stats {count, seconds, timers}. Safe to call repeatedly
    (resets per-build timing state), so both the CLI and the server use it.
    """
    global AUTHOR_LOGIN, _T0
    _T0 = time.perf_counter()
    _TIMERS.clear()
    _COUNTS.clear()
    LOG_LINES.clear()
    _CONTRIB_CACHE.clear()

    log("inicio")
    AUTHOR_LOGIN = run(["gh", "api", "user", "--jq", ".login"]).strip()
    log(f"usuario: {AUTHOR_LOGIN}")

    _t = time.perf_counter()
    prs = fetch_open_prs()
    log(f"PRs abiertas encontradas: {len(prs)} ({time.perf_counter() - _t:.1f}s)")

    _t = time.perf_counter()
    enriched = [e for e in (enrich(p["url"]) for p in prs) if e is not None]
    enriched.sort(key=lambda p: p["updatedAt"], reverse=True)
    log(f"PRs enriquecidas: {len(enriched)} ({time.perf_counter() - _t:.1f}s)")

    now = datetime.now(timezone(timedelta(hours=-4)))  # Santiago (CLT)
    stamp = now.strftime("%Y-%m-%d · %H:%M -04")

    _t = time.perf_counter()
    fragment = TEMPLATE.read_text(encoding="utf-8")
    fragment = fragment.replace("__PR_DATA__", json.dumps(enriched, ensure_ascii=False))
    fragment = fragment.replace("__GENERATED_AT__", stamp)
    fragment = fragment.replace("__AUTHOR__", AUTHOR_LOGIN)

    title_m = re.search(r"<title>(.*?)</title>", fragment, flags=re.S)
    title = title_m.group(1).strip() if title_m else "Mis PRs"
    if title_m:
        fragment = fragment.replace(title_m.group(0), "", 1)

    html = (
        '<!doctype html>\n<html lang="es">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n</head>\n<body>\n{fragment}\n</body>\n</html>\n"
    )
    # Atomic write: never serve a half-written file to a concurrent GET.
    tmp = OUTPUT.with_suffix(".html.tmp")
    tmp.write_text(html, encoding="utf-8")
    os.replace(tmp, OUTPUT)
    log(f"HTML escrito: {len(html):,} bytes ({time.perf_counter() - _t:.1f}s)")

    log("desglose de llamadas a gh:")
    for key in sorted(_TIMERS, key=lambda k: -_TIMERS[k]):
        log(f"    · {key}: {_TIMERS[key]:.1f}s en {_COUNTS[key]} llamadas")

    seconds = time.perf_counter() - _T0
    log(f"LISTO — {len(enriched)} PRs en {seconds:.1f}s totales")
    return {"count": len(enriched), "seconds": round(seconds, 1), "timers": dict(_TIMERS)}


def main() -> int:
    """CLI entry: build once (honoring the --scheduled work-hours guard)."""
    if "--scheduled" in sys.argv and not within_work_hours():
        print("skip: fuera de horario laboral (L-V 09:00-18:30)")
        return 0
    stats = build_dashboard()
    print(f"OK {stats['count']} PRs -> {OUTPUT}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # surface the reason to the scheduled run
        print(f"BUILD FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
