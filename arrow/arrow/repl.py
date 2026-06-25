"""Interactive terminal loop (Ollama-style: short prompts, simple commands)."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from arrow.analysis import (
    format_explain_rank_fallback,
    naive_deterministic_fit,
    run_explain_rank,
    run_summarize_notice,
)
from arrow.company_profile import (
    default_profile_path,
    init_company_profile_file,
    load_company_profile,
    save_company_profile,
)
from arrow.ollama_client import analysis_model_name, ollama_host, ollama_tags
from arrow.ollama_runtime import ensure_ollama_running
from arrow.ranking import rank_rows_by_profile, without_fit_metadata
from arrow.repo import MAX_LIST_LIMIT, OpportunityRepo
from arrow.ipv4_preference import enable_ipv4_preference
from arrow.sync_engine import sync_from_bulk_csv, sync_full_csv_from_url


def _term_width() -> int:
    try:
        return shutil.get_terminal_size().columns or 80
    except Exception:
        return 80


def _print_header(title: str) -> None:
    w = _term_width()
    line = "─" * min(w - 2, 78)
    print(f"\n\033[1m{title}\033[0m\n{line}")


def _short_line(i: int, row: Dict[str, Any]) -> str:
    title = str(row.get("title") or "")[:60]
    sol = str(row.get("solicitationNumber") or row.get("noticeId") or "")[:24]
    posted = str(row.get("postedDate") or "")
    return f"  [{i}] {posted}  {sol}  {title}"


def _print_list(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        print("  (no results)")
        return
    for i, row in enumerate(rows, start=1):
        print(_short_line(i, row))
    print(f"\n  \033[2m{len(rows)} item(s). Type a number for full JSON, or another command.\033[0m")


def _print_detail(row: Dict[str, Any]) -> None:
    print(json.dumps(row, indent=2, ensure_ascii=False))


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(s.strip())
    except Exception:
        return None


def _strip_wrapping_quotes(s: str) -> str:
    t = s.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1].strip()
    return t


class ArrowRepl:
    def __init__(self, repo: OpportunityRepo) -> None:
        self.repo = repo
        self.last_rows: List[Dict[str, Any]] = []

    def cmd_list(self, parts: List[str]) -> None:
        n = 10
        if len(parts) >= 2:
            if parts[1].lower() == "all":
                n = self.repo.count_opportunities()
                if n < 1:
                    print("  Local DB is empty. Run: sync bulk auto")
                    return
                n = min(n, MAX_LIST_LIMIT)
            else:
                v = _parse_int(parts[1])
                if v in (5, 10, 20):
                    n = v
                elif v is not None and 1 <= v <= MAX_LIST_LIMIT:
                    n = v
                else:
                    print(f"  Use: list [5|10|20] | list all | list <1-{MAX_LIST_LIMIT}>")
                    return
        if self.repo.count_opportunities() == 0:
            print("  Local DB is empty. Run: sync bulk auto")
            return
        rows = self.repo.list_recent(n)
        self.last_rows = rows
        _print_header(f"Recent opportunities (local DB, top {n})")
        _print_list(rows)

    def cmd_search(self, parts: List[str]) -> None:
        if len(parts) < 2:
            print("  Usage: search title <words...>   |   search id <noticeId>")
            return
        kind = parts[1].lower()
        rest = " ".join(parts[2:]).strip()
        if self.repo.count_opportunities() == 0:
            print("  Local DB is empty. Run: sync bulk auto")
            return
        if kind == "id":
            if not rest:
                print("  Usage: search id <noticeId>")
                return
            rows = self.repo.search_notice_id(rest)
            self.last_rows = rows
            _print_header(f"Search by id (local): {rest}")
            _print_list(rows)
            return
        if kind == "title":
            if not rest:
                print("  Usage: search title <words...>")
                return
            rows = self.repo.search_title(rest, limit=MAX_LIST_LIMIT)
            self.last_rows = rows
            _print_header(f"Search title (local): {rest}")
            _print_list(rows)
            return
        print("  Usage: search title <words...>   |   search id <noticeId>")

    def cmd_select(self, idx: int) -> None:
        if not self.last_rows:
            print("  No list loaded. Run list or search first.")
            return
        if idx < 1 or idx > len(self.last_rows):
            print(f"  Pick 1–{len(self.last_rows)}.")
            return
        row = self.last_rows[idx - 1]
        base = without_fit_metadata(row)
        nid = str(base.get("noticeId") or "").strip()
        full = self.repo.get_raw_dict(nid) if nid else None
        detail = dict(full if full is not None else base)
        _print_header(f"Detail [{idx}] {row.get('solicitationNumber') or row.get('noticeId')}")
        _print_detail(detail)

    def cmd_sync(self, parts: List[str]) -> None:
        if len(parts) < 2:
            print("  Usage: sync bulk auto   |   sync bulk <file.csv>")
            return
        sub = parts[1].lower()
        if sub == "bulk":
            if len(parts) >= 3 and parts[2].lower() == "auto":
                summary = sync_full_csv_from_url(self.repo, skip_if_unchanged=True)
                if summary.get("skipped"):
                    print(
                        f"  Full CSV unchanged (sha256); ingest skipped.\n"
                        f"  File: {summary.get('path', '')}"
                    )
                    return
                print(
                    f"  Bulk (download) OK: run #{summary['run_id']}  "
                    f"seen={summary['total_seen']}  new={summary['new_count']}  "
                    f"changed={summary['changed_count']}  missing={summary['missing_count']}"
                )
                print(f"  Cached: {summary.get('cached_path', '')}  sha256={summary.get('sha256', '')[:16]}…")
                return
            path_str = " ".join(parts[2:]).strip() if len(parts) > 2 else ""
            if not path_str:
                path_str = (os.environ.get("ARROW_BULK_CSV") or "").strip()
            if not path_str:
                print(
                    "  Usage: sync bulk auto   (download official full CSV from SAM.gov)\n"
                    "         sync bulk <path-to.csv>   (or set ARROW_BULK_CSV)"
                )
                return
            summary = sync_from_bulk_csv(self.repo, Path(path_str), cache=True)
            print(
                f"  Bulk OK: run #{summary['run_id']}  "
                f"seen={summary['total_seen']}  new={summary['new_count']}  "
                f"changed={summary['changed_count']}  missing={summary['missing_count']}"
            )
            print(f"  Cached: {summary.get('cached_path', '')}")
            return
        print("  Usage: sync bulk auto   |   sync bulk <file.csv>")

    def cmd_status(self) -> None:
        n = self.repo.count_opportunities()
        r = self.repo.last_sync_run()
        print(f"  Opportunities in DB: {n}")
        if not r:
            print("  No sync runs yet. Run: sync bulk auto")
            return
        print(
            f"  Last sync: #{r['id']} {r['source_type']}  status={r['status']}  "
            f"seen={r['total_seen']}  new={r['new_count']}  changed={r['changed_count']}"
        )
        if r["started_at"]:
            print(f"  Started: {r['started_at']}")
        if r["finished_at"]:
            print(f"  Finished: {r['finished_at']}")

    def cmd_changed(self) -> None:
        rows = self.repo.list_changed_multi_snapshot(20)
        self.last_rows = rows
        _print_header("Changed (multiple snapshots, top 20)")
        _print_list(rows)

    def cmd_save(self, parts: List[str]) -> None:
        if len(parts) < 2:
            print("  Usage: save <n>   (row number from last list)")
            return
        idx = _parse_int(parts[1])
        if idx is None or idx < 1:
            print("  Invalid row number.")
            return
        if not self.last_rows or idx > len(self.last_rows):
            print("  No such row in the last list.")
            return
        row = self.last_rows[idx - 1]
        nid = str(row.get("noticeId") or "").strip()
        if not nid:
            print("  Row has no noticeId.")
            return
        self.repo.save_item(nid, source="repl")
        print(f"  Saved notice_id={nid} (saved_items)")

    def cmd_saved(self) -> None:
        rows = self.repo.list_saved(MAX_LIST_LIMIT)
        self.last_rows = rows
        _print_header("Saved items (local DB)")
        _print_list(rows)

    def cmd_diff(self, parts: List[str]) -> None:
        print("  diff: coming in Phase 4 (field-level diff vs snapshots).")

    def cmd_profile(self, line: str) -> None:
        parts = line.strip().split(maxsplit=1)
        if not parts or parts[0].lower() != "profile":
            return
        rest = (parts[1] if len(parts) > 1 else "").strip()
        if not rest or rest.lower() == "show":
            p = load_company_profile()
            _print_header("Company profile")
            print(json.dumps(p, indent=2, ensure_ascii=False))
            print(f"\n  File: {default_profile_path()}")
            return
        head, _, tail = rest.partition(" ")
        sub = head.lower()
        if sub == "path":
            print(f"  {default_profile_path()}")
            return
        if sub == "init":
            init_company_profile_file()
            print(f"  Template: {default_profile_path()}")
            return
        if sub == "mission":
            p = load_company_profile()
            p["mission"] = _strip_wrapping_quotes(tail.strip())
            save_company_profile(p)
            print("  Updated mission.")
            return
        if sub == "notes":
            p = load_company_profile()
            p["notes"] = _strip_wrapping_quotes(tail.strip())
            save_company_profile(p)
            print("  Updated notes.")
            return
        if sub == "naics":
            p = load_company_profile()
            p["target_naics"] = [x.strip() for x in tail.replace(";", ",").split(",") if x.strip()]
            save_company_profile(p)
            print("  Updated target_naics.")
            return
        print(
            "  Usage: profile | profile path | profile init | profile mission <text> | "
            "profile notes <text> | profile naics 541511,541512"
        )

    def cmd_why(self, parts: List[str]) -> None:
        if len(parts) < 2:
            print("  Usage: why <n>   (row from last list; Ollama + company profile)")
            return
        idx = _parse_int(parts[1])
        if idx is None or idx < 1:
            print("  Invalid row number.")
            return
        if not self.last_rows or idx > len(self.last_rows):
            print("  No such row in the last list. Run list or search first.")
            return
        profile = load_company_profile()
        if not (
            str(profile.get("mission") or "").strip()
            or str(profile.get("notes") or "").strip()
            or profile.get("target_naics")
        ):
            print("  Profile empty. Try: profile init   then edit JSON, or profile mission …")
            return
        row = self.last_rows[idx - 1]
        base = without_fit_metadata(row)
        nid = str(base.get("noticeId") or "").strip()
        full = self.repo.get_raw_dict(nid) if nid else None
        notice = dict(full if full is not None else base)
        det = naive_deterministic_fit(profile, notice)
        try:
            parsed, raw = run_explain_rank(profile, notice)
        except Exception as e:
            print(f"  Model error: {e}")
            print(format_explain_rank_fallback(det))
            return
        if parsed is not None:
            _print_header(f"Why [{idx}] ({analysis_model_name()})")
            print(json.dumps(parsed.model_dump(), indent=2, ensure_ascii=False))
            print(
                f"\n  \033[2mDeterministic hint: fit={float(det.get('total') if det.get('total') is not None else 0.0):.4f} (0–1) "
                f"{det.get('components')}\033[0m"
            )
        else:
            print(format_explain_rank_fallback(det))
            tail = (raw or "")[:1800]
            if tail.strip():
                print(f"\n  \033[2mRaw (truncated):\n{tail}\033[0m")

    def cmd_rank(self, parts: List[str]) -> None:
        n = 50
        if len(parts) >= 2:
            v = _parse_int(parts[1])
            if v is not None and 1 <= v <= MAX_LIST_LIMIT:
                n = v
        profile = load_company_profile()
        if not (
            str(profile.get("mission") or "").strip()
            or str(profile.get("notes") or "").strip()
            or profile.get("target_naics")
        ):
            print("  Profile empty. Set: profile mission …  or profile init + edit JSON.")
            return
        rows = self.repo.list_recent(n)
        ranked = rank_rows_by_profile(profile, rows)
        self.last_rows = ranked
        _print_header(
            f"Ranked leads (fit 0–1, top {min(20, len(ranked))} of {len(ranked)} by profile)"
        )
        for i, row in enumerate(ranked[:20], start=1):
            inner = without_fit_metadata(row)
            sc = float(row.get("_fit_total")) if row.get("_fit_total") is not None else 0.0
            title = str(inner.get("title") or "")[:58]
            sol = str(inner.get("solicitationNumber") or inner.get("noticeId") or "")[:22]
            posted = str(inner.get("postedDate") or "")
            print(f"  [{i}] {sc:5.2f}  {posted}  {sol}  {title}")

    def cmd_summarize(self, parts: List[str]) -> None:
        if len(parts) < 2:
            print("  Usage: summarize <n>   (row from last list; needs ARROW_ANALYSIS_MODEL)")
            return
        idx = _parse_int(parts[1])
        if idx is None or idx < 1 or not self.last_rows or idx > len(self.last_rows):
            print("  Invalid row or no list loaded.")
            return
        profile = load_company_profile()
        row = self.last_rows[idx - 1]
        base = without_fit_metadata(row)
        nid = str(base.get("noticeId") or "").strip()
        full = self.repo.get_raw_dict(nid) if nid else None
        notice = dict(full if full is not None else base)
        try:
            parsed, _raw = run_summarize_notice(profile, notice)
        except Exception as e:
            print(f"  Summarize error: {e}")
            return
        if parsed:
            _print_header(f"Summarize [{idx}]")
            print(json.dumps(parsed.model_dump(), indent=2, ensure_ascii=False))
        else:
            print("  Model returned invalid JSON. Try ollama ping or a smaller description.")

    def cmd_ollama(self, parts: List[str]) -> None:
        if len(parts) < 2 or parts[1].lower() != "ping":
            print("  Usage: ollama ping   (GET /api/tags on OLLAMA_HOST)")
            return
        try:
            j = ollama_tags()
            names = sorted({str(m.get("name", "")) for m in j.get("models", []) if m.get("name")})
            tail = ", ".join(names) if names else "(none)"
            if len(tail) > 500:
                tail = tail[:500] + "…"
            print(f"  OK  {ollama_host()}\n  Models: {tail}")
        except Exception as e:
            print(f"  Ollama unreachable: {e}")

    def cmd_help(self) -> None:
        print(
            f"""
  Commands:
    sync bulk auto      Download official ContractOpportunitiesFullCSV + ingest
    sync bulk <path>    Ingest local CSV; copies to ~/.arrow/cache/ (or ARROW_BULK_CSV)
    status              DB + last sync run summary
    list [5|10|20]      Recent from local DB (default 10; any 1–{MAX_LIST_LIMIT})
    list all            All rows in local DB (up to {MAX_LIST_LIMIT})
    search title ...    Search title in local DB
    search id ...       Lookup notice id / solicitation in local DB
    changed             Rows with multiple snapshots (content changed)
    save <n>            Save row n from last list into saved_items
    saved               List saved_items joined to opportunities
    ui                  Full-screen menu (arrows): sync, browse, search; Tab→rank list, saved, exports
    <number>            Full JSON (raw_json from local DB)
    diff <n>            Placeholder (Phase 4)
    profile             Show company profile (rank / why context)
    profile path        Print path to company_profile.json
    profile init        Write template ~/.arrow/company_profile.json
    profile mission …   Set mission (rest of line)
    profile notes …     Set notes
    profile naics a,b   Set target NAICS list
    why <n>             Explain fit vs profile (Ollama + ARROW_ANALYSIS_MODEL)
    summarize <n>       Short structured summary (Ollama + ARROW_ANALYSIS_MODEL)
    rank [n]            Rank recent DB rows (1–{MAX_LIST_LIMIT}); fit score 0–1; sets last list
    ollama ping         Check local Ollama (OLLAMA_HOST)
    help / quit

  Data: ~/.arrow/arrow.db  ~/.arrow/cache/
  Keys: OLLAMA_HOST | ARROW_ANALYSIS_MODEL=<ollama model tag>
        ARROW_NO_AUTO_OLLAMA=1  disables auto-start of `ollama serve`
""".strip()
        )

    def cmd_ui(self) -> None:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            print("  UI requires a real TTY terminal (don’t pipe Arrow).")
            return

        from arrow.archive_store import ArchiveStore
        from arrow.tui import ArrowTui

        exports = ArchiveStore()
        title = "Results"
        if self.last_rows:
            title = f"Results ({len(self.last_rows)})"
        ArrowTui(
            self.repo,
            exports,
            initial_rows=self.last_rows,
            initial_title=title,
        ).run()

    def run(self) -> None:
        print(
            "\033[1mArrow\033[0m — local SAM intelligence (type \033[1mhelp\033[0m)\n"
            "  Tip: \033[1msync bulk auto\033[0m + \033[1mprofile mission …\033[0m; optional Ollama for why/summarize.\n"
        )
        while True:
            try:
                line = input("\033[1m>>>\033[0m ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line.lower() in ("quit", "exit", "q"):
                break
            if line.lower() == "help":
                self.cmd_help()
                continue

            m = re.fullmatch(r"(\d+)", line)
            if m:
                self.cmd_select(int(m.group(1)))
                continue

            parts = line.split()
            cmd = parts[0].lower()
            try:
                if cmd == "sync":
                    self.cmd_sync(parts)
                elif cmd == "list":
                    self.cmd_list(parts)
                elif cmd == "search":
                    self.cmd_search(parts)
                elif cmd == "status":
                    self.cmd_status()
                elif cmd == "changed":
                    self.cmd_changed()
                elif cmd == "save":
                    self.cmd_save(parts)
                elif cmd == "saved":
                    self.cmd_saved()
                elif cmd == "diff":
                    self.cmd_diff(parts)
                elif cmd == "ui":
                    self.cmd_ui()
                elif cmd == "profile":
                    self.cmd_profile(line)
                elif cmd == "why":
                    self.cmd_why(parts)
                elif cmd == "summarize":
                    self.cmd_summarize(parts)
                elif cmd == "rank":
                    self.cmd_rank(parts)
                elif cmd == "ollama":
                    self.cmd_ollama(parts)
                else:
                    print(f"  Unknown command: {cmd}. Try help.")
            except Exception as e:
                print(f"  Error: {e}", file=sys.stderr)

        try:
            self.repo.close()
        except Exception:
            pass
        print("  Goodbye.\n")


def main() -> None:
    enable_ipv4_preference()
    from arrow.env import load_dotenv_if_present

    load_dotenv_if_present()
    ensure_ollama_running(quiet=True)
    repo = OpportunityRepo()
    ArrowRepl(repo).run()


if __name__ == "__main__":
    main()
