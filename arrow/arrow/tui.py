"""Arrow full-screen TUI: Ollama-style menus (arrows + Enter + Esc), no letter hotkeys."""

from __future__ import annotations

import curses
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_ENTER = (10, 13, getattr(curses, "KEY_ENTER", -999))


def _is_row_delete_ch(ch: int) -> bool:
    """Forward Delete (KEY_DC) or typical Mac/backspace (127) — terminals disagree on labels."""
    keys: List[int] = [curses.KEY_DC, 127, 8]
    kb = getattr(curses, "KEY_BACKSPACE", None)
    if kb is not None:
        keys.append(int(kb))
    return ch in keys

from arrow.analysis import (
    format_explain_rank_fallback,
    naive_deterministic_fit,
    run_explain_rank,
    run_summarize_notice,
)
from arrow.archive_store import ArchiveStore, ArchivedItem
from arrow.company_profile import (
    default_profile_path,
    init_company_profile_file,
    load_company_profile,
    save_company_profile,
)
from arrow.ollama_client import analysis_model_name
from arrow.ollama_runtime import ensure_ollama_running
from arrow.ranking import rank_rows_by_profile, without_fit_metadata
from arrow.repo import MAX_LIST_LIMIT, OpportunityRepo
from arrow.ipv4_preference import enable_ipv4_preference
from arrow.sync_engine import sync_from_bulk_csv, sync_full_csv_from_url


def _clip(s: str, n: int) -> str:
    if n <= 0:
        return ""
    return s if len(s) <= n else s[: max(0, n - 1)] + "…"


def _put_status(stdscr: "curses._CursesWindow", y: int, x: int, text: str) -> None:
    """Single-line status (addnstr requires a max-width arg; use addstr + clip)."""
    _, w = stdscr.getmaxyx()
    s = _clip(text, max(1, w - x - 1))
    try:
        stdscr.addstr(y, x, s)
    except curses.error:
        pass


def _wrap_json_lines_for_display(lines: List[str], width: int) -> List[str]:
    """Split long JSON lines so the detail view does not clip mid-string (looks like broken JSON)."""
    w = max(1, width)
    out: List[str] = []
    for line in lines:
        if not line:
            out.append("")
            continue
        for i in range(0, len(line), w):
            out.append(line[i : i + w])
    return out


def _row_title(row: Dict[str, Any]) -> str:
    return str(row.get("title") or "")


def _row_id(row: Dict[str, Any]) -> str:
    return str(row.get("solicitationNumber") or row.get("noticeId") or "")


def _row_posted(row: Dict[str, Any]) -> str:
    return str(row.get("postedDate") or "")


def _notice_id(row: Dict[str, Any]) -> str:
    for k in ("noticeId", "notice_id"):
        v = row.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _browse_list_line(row: Dict[str, Any], w: int) -> str:
    fit = row.get("_fit_total")
    if fit is not None:
        try:
            fs = float(fit)
        except (TypeError, ValueError):
            fs = 0.0
        line = f"{fs:5.2f}  {_row_posted(row):10}  {_clip(_row_id(row), 14):14}  {_row_title(row)}"
    else:
        line = f"{_row_posted(row):10}  {_clip(_row_id(row), 20):20}  {_row_title(row)}"
    return _clip(line, max(1, w - 2))


@dataclass
class ListState:
    rows: List[Dict[str, Any]]
    selected: int = 0
    title: str = ""


class ArrowTui:
    """Home menu drives sync, browse, search, saved (DB), JSON exports, status — arrow keys only."""

    def __init__(
        self,
        repo: OpportunityRepo,
        exports: Optional[ArchiveStore] = None,
        *,
        initial_rows: Optional[List[Dict[str, Any]]] = None,
        initial_title: str = "",
    ) -> None:
        self.repo = repo
        self.exports = exports or ArchiveStore()
        self._toast = ""
        self._initial_rows = initial_rows
        self._initial_title = initial_title

    def run(self) -> None:
        ensure_ollama_running(quiet=True)
        curses.wrapper(self._app)

    def _toast_set(self, msg: str) -> None:
        self._toast = msg

    def _draw_brand(self, stdscr: "curses._CursesWindow", subtitle: str = "") -> None:
        h, w = stdscr.getmaxyx()
        stdscr.attron(curses.A_BOLD)
        stdscr.addnstr(0, 0, _clip("Arrow", w - 1), w - 1)
        stdscr.attroff(curses.A_BOLD)
        if subtitle:
            stdscr.attron(curses.A_DIM)
            stdscr.addnstr(0, 8, _clip("  " + subtitle, w - 9), max(0, w - 9))
            stdscr.attroff(curses.A_DIM)
        stdscr.attron(curses.A_DIM)
        stdscr.hline(1, 0, curses.ACS_HLINE, w - 1)
        stdscr.attroff(curses.A_DIM)

    def _footer(self, stdscr: "curses._CursesWindow", hint: str) -> None:
        h, w = stdscr.getmaxyx()
        msg = self._toast
        self._toast = ""
        line = _clip(f"{hint}   {msg}".strip(), w - 1)
        stdscr.attron(curses.A_DIM)
        try:
            stdscr.addnstr(h - 1, 0, " " * (w - 1), w - 1)
            stdscr.addnstr(h - 1, 0, line, w - 1)
        except curses.error:
            pass
        stdscr.attroff(curses.A_DIM)

    def _menu_loop(
        self,
        stdscr: "curses._CursesWindow",
        *,
        title: str,
        items: List[Tuple[str, str]],
        footer_hint: str,
    ) -> Optional[str]:
        """Return tag on Enter, None on Esc (caller treats as back)."""
        sel = 0
        while True:
            stdscr.erase()
            self._draw_brand(stdscr, title)
            h, w = stdscr.getmaxyx()
            top = 3
            body_h = max(1, h - top - 2)
            n = len(items)
            sel = max(0, min(sel, n - 1))
            start = max(0, sel - body_h + 1) if sel >= body_h else 0
            for i in range(start, min(n, start + body_h)):
                label = items[i][1]
                y = top + (i - start)
                if i == sel:
                    stdscr.attron(curses.A_REVERSE)
                    stdscr.addnstr(y, 2, _clip(label, w - 4), w - 4)
                    stdscr.attroff(curses.A_REVERSE)
                else:
                    stdscr.addnstr(y, 2, _clip(label, w - 4), w - 4)
            self._footer(stdscr, footer_hint)
            stdscr.refresh()
            ch = stdscr.getch()
            if ch in (27,):
                return None
            if ch in (curses.KEY_UP,):
                sel = max(0, sel - 1)
            elif ch in (curses.KEY_DOWN,):
                sel = min(n - 1, sel + 1)
            elif ch in _ENTER:
                return items[sel][0]

    def _read_line(
        self,
        stdscr: "curses._CursesWindow",
        *,
        title: str,
        prompt: str,
        initial: str = "",
    ) -> Optional[str]:
        buf = list(initial)
        curses.curs_set(1)
        try:
            while True:
                stdscr.erase()
                self._draw_brand(stdscr, title)
                stdscr.addnstr(3, 2, _clip(prompt, stdscr.getmaxyx()[1] - 4), stdscr.getmaxyx()[1] - 4)
                line = "".join(buf)
                stdscr.addnstr(5, 2, _clip(line + " ", stdscr.getmaxyx()[1] - 4), stdscr.getmaxyx()[1] - 4)
                self._footer(stdscr, "Enter confirm  Esc cancel  Backspace erase")
                stdscr.refresh()
                ch = stdscr.getch()
                if ch in (27,):
                    return None
                if ch in _ENTER:
                    return "".join(buf).strip()
                if ch in (curses.KEY_BACKSPACE, 127, 8):
                    if buf:
                        buf.pop()
                elif 32 <= ch <= 126:
                    buf.append(chr(ch))
        finally:
            curses.curs_set(0)

    def _message_screen(self, stdscr: "curses._CursesWindow", title: str, body: str) -> None:
        """Scroll long text; only Enter/Esc dismiss (other keys scroll when content overflows)."""
        max_body = 400_000
        if len(body) > max_body:
            body = body[:max_body] + "\n…(truncated)"
        h, w = stdscr.getmaxyx()
        col_w = max(1, w - 4)
        inner_h = max(1, h - 6)
        raw_lines = body.splitlines() or [""]
        # Hard-wrap (no mid-line ellipsis) so JSON / long bullets stay readable like detail view.
        lines = _wrap_json_lines_for_display(raw_lines, col_w)
        offset = 0
        scrollable = len(lines) > inner_h
        while True:
            stdscr.erase()
            self._draw_brand(stdscr, title)
            y = 3
            end = min(len(lines), offset + inner_h)
            for i in range(offset, end):
                seg = lines[i]
                try:
                    stdscr.addnstr(y, 2, seg, col_w)
                except curses.error:
                    pass
                y += 1
            if scrollable:
                pct = int(100 * (offset + inner_h) / max(1, len(lines)))
                hint = f"↑↓ PgUp/PgDn scroll  {pct}%  Enter/Esc close"
            else:
                hint = "Enter or Esc to continue"
            self._footer(stdscr, hint)
            stdscr.refresh()
            ch = stdscr.getch()
            if ch in _ENTER or ch == 27:
                break
            if not scrollable:
                continue
            if ch == curses.KEY_DOWN:
                offset = min(max(0, len(lines) - inner_h), offset + 1)
            elif ch == curses.KEY_UP:
                offset = max(0, offset - 1)
            elif ch == curses.KEY_NPAGE:
                offset = min(max(0, len(lines) - inner_h), offset + inner_h)
            elif ch == curses.KEY_PPAGE:
                offset = max(0, offset - inner_h)

    def _run_sync_bulk_auto(self, stdscr: "curses._CursesWindow") -> None:
        try:
            stdscr.erase()
            self._draw_brand(stdscr, "Full CSV download")
            _put_status(stdscr, 3, 2, "Downloading ContractOpportunitiesFullCSV from SAM.gov…")
            stdscr.refresh()
            summary = sync_full_csv_from_url(self.repo, skip_if_unchanged=True)
            if summary.get("skipped"):
                self._message_screen(
                    stdscr,
                    "Full CSV unchanged",
                    f"SHA256 matches last ingest; DB update skipped.\n{summary.get('path', '')}",
                )
                return
            self._message_screen(
                stdscr,
                "Full CSV done",
                f"Run #{summary['run_id']}\n"
                f"Seen: {summary['total_seen']}\n"
                f"New: {summary['new_count']}\n"
                f"Changed: {summary['changed_count']}\n"
                f"Missing: {summary['missing_count']}\n"
                f"File: {summary.get('cached_path', '')}",
            )
        except Exception as e:
            self._message_screen(stdscr, "Full CSV failed", str(e))

    def _run_sync_bulk(self, stdscr: "curses._CursesWindow") -> None:
        default = os.environ.get("ARROW_BULK_CSV", "").strip()
        path_s = self._read_line(
            stdscr,
            title="Bulk CSV",
            prompt="Path to ContractOpportunitiesFullCSV (empty = ARROW_BULK_CSV):",
            initial=default,
        )
        if path_s is None:
            return
        if not path_s:
            self._toast_set("No path")
            return
        try:
            stdscr.erase()
            self._draw_brand(stdscr, "Bulk CSV")
            _put_status(stdscr, 3, 2, "Importing CSV (may take a while)…")
            stdscr.refresh()
            summary = sync_from_bulk_csv(self.repo, Path(path_s), cache=True)
            self._message_screen(
                stdscr,
                "Bulk CSV done",
                f"Run #{summary['run_id']}\n"
                f"Seen: {summary['total_seen']}\n"
                f"New: {summary['new_count']}\n"
                f"Changed: {summary['changed_count']}\n"
                f"Missing: {summary['missing_count']}\n"
                f"Cached: {summary.get('cached_path', '')}",
            )
        except Exception as e:
            self._message_screen(stdscr, "Bulk CSV failed", str(e))

    def _pick_count(
        self,
        stdscr: "curses._CursesWindow",
        *,
        db_total: Optional[int] = None,
    ) -> Optional[int]:
        items: List[Tuple[str, str]] = [
            ("5", "5 rows"),
            ("10", "10 rows"),
            ("20", "20 rows"),
            ("50", "50 rows"),
            ("100", "100 rows"),
            ("200", "200 rows"),
            ("500", "500 rows"),
            ("1000", "1000 rows"),
            ("5000", "5000 rows"),
            ("10000", "10000 rows"),
            ("20000", "20000 rows"),
            ("35000", "35000 rows"),
            ("50000", "50000 rows"),
        ]
        if db_total is not None and db_total > 0:
            items.append(("all", f"All in DB ({db_total}, cap {MAX_LIST_LIMIT})"))
        tag = self._menu_loop(
            stdscr,
            title="How many?",
            items=items,
            footer_hint="↑↓  ↵ select  Esc cancel",
        )
        if not tag:
            return None
        if tag == "all":
            if not db_total:
                return None
            return min(int(db_total), MAX_LIST_LIMIT)
        return int(tag)

    def _notice_payload(self, row: Dict[str, Any]) -> Dict[str, Any]:
        base = without_fit_metadata(row)
        nid = str(base.get("noticeId") or "").strip()
        full = self.repo.get_raw_dict(nid) if nid else None
        d = dict(full if full is not None else base)
        return d

    def _run_company_profile(self, stdscr: "curses._CursesWindow") -> None:
        items = [
            ("show", "Show current profile"),
            ("path", "Print file path"),
            ("init", "Create template file if missing"),
            ("mission", "Set mission (prompt)…"),
            ("notes", "Set notes (prompt)…"),
            ("naics_show", "Preferred NAICS (list)…"),
            ("naics_set", "Preferred NAICS (edit comma-list)…"),
            ("back", "Back"),
        ]
        while True:
            tag = self._menu_loop(stdscr, title="Company profile", items=items, footer_hint="↑↓  ↵  Esc back")
            if tag is None or tag == "back":
                return
            if tag == "show":
                p = load_company_profile()
                self._message_screen(stdscr, "Profile", json.dumps(p, indent=2, ensure_ascii=False))
            elif tag == "path":
                self._message_screen(stdscr, "Path", str(default_profile_path()))
            elif tag == "init":
                init_company_profile_file()
                self._toast_set("Profile template ready")
            elif tag == "mission":
                t = self._read_line(stdscr, title="Mission", prompt="Mission (one line):")
                if t is not None and t.strip():
                    p = load_company_profile()
                    p["mission"] = t.strip()
                    save_company_profile(p)
                    self._toast_set("Mission saved")
            elif tag == "notes":
                t = self._read_line(stdscr, title="Notes", prompt="Notes (one line):")
                if t is not None and t.strip():
                    p = load_company_profile()
                    p["notes"] = t.strip()
                    save_company_profile(p)
                    self._toast_set("Notes saved")
            elif tag == "naics_show":
                p = load_company_profile()
                codes = p.get("target_naics") or []
                if not codes:
                    self._message_screen(
                        stdscr,
                        "Preferred NAICS",
                        "(none set)\n\nUse “Preferred NAICS (edit comma-list)” to add codes for ranking / why fit.",
                    )
                else:
                    body = "Preferred NAICS (target_naics):\n\n" + "\n".join(f"  • {c}" for c in codes)
                    self._message_screen(stdscr, "Preferred NAICS", body)
            elif tag == "naics_set":
                p = load_company_profile()
                cur = ", ".join(p.get("target_naics") or [])
                t = self._read_line(
                    stdscr,
                    title="Preferred NAICS",
                    prompt="Codes separated by commas (e.g. 336111, 532111):",
                    initial=cur,
                )
                if t is not None:
                    p["target_naics"] = [x.strip() for x in t.replace(";", ",").split(",") if x.strip()]
                    save_company_profile(p)
                    self._toast_set("Preferred NAICS saved")

    def _browse_opportunities(
        self,
        stdscr: "curses._CursesWindow",
        state: ListState,
        *,
        footer_extra: str = "",
        on_delete_notice: Optional[Callable[[str], bool | None]] = None,
    ) -> None:
        rows = state.rows
        sel = state.selected
        while True:
            stdscr.erase()
            self._draw_brand(stdscr, state.title)
            h, w = stdscr.getmaxyx()
            top = 3
            body_h = max(1, h - top - 2)
            if not rows:
                stdscr.addnstr(top, 2, "(no rows)", w - 4)
                self._footer(stdscr, f"Esc back  {footer_extra}".strip())
                stdscr.refresh()
                ch = stdscr.getch()
                if ch in (27,):
                    return
                continue
            sel = max(0, min(sel, len(rows) - 1))
            start = max(0, sel - body_h + 1) if sel >= body_h else 0
            for i in range(start, min(len(rows), start + body_h)):
                row = rows[i]
                line = _browse_list_line(row, w)
                y = top + (i - start)
                if i == sel:
                    stdscr.attron(curses.A_REVERSE)
                    stdscr.addnstr(y, 1, line, w - 2)
                    stdscr.attroff(curses.A_REVERSE)
                else:
                    stdscr.addnstr(y, 1, line, w - 2)
            hint = "↑↓  ↵ detail  Tab (rank list, save, …)  Esc back"
            if on_delete_notice:
                hint += "  Del/⌫ unsave"
            if footer_extra:
                hint += "  " + footer_extra
            self._footer(stdscr, hint)
            stdscr.refresh()
            ch = stdscr.getch()
            if ch in (27,):
                return
            if ch in (curses.KEY_UP,):
                sel = max(0, sel - 1)
            elif ch in (curses.KEY_DOWN,):
                sel = min(len(rows) - 1, sel + 1)
            elif ch in _ENTER:
                self._detail_screen(stdscr, rows[sel])
            elif ch == 9:  # Tab
                self._row_actions_menu(stdscr, rows[sel], browse_state=state)
            elif on_delete_notice and _is_row_delete_ch(ch):
                nid = _notice_id(rows[sel])
                if not nid:
                    self._toast_set("Row has no notice id")
                    continue
                try:
                    ok = on_delete_notice(nid)
                    if ok is False:
                        self._toast_set("Not in saved list (already removed?)")
                        continue
                    rows.pop(sel)
                    if not rows:
                        return
                    sel = min(sel, len(rows) - 1)
                    self._toast_set("Removed from saved")
                except Exception as e:
                    self._toast_set(str(e))

    def _browse_export_files(
        self,
        stdscr: "curses._CursesWindow",
        items: List[ArchivedItem],
    ) -> None:
        sel = 0
        rows = [it.item for it in items]
        while True:
            stdscr.erase()
            self._draw_brand(stdscr, "JSON file copies (~/.arrow/archive)")
            h, w = stdscr.getmaxyx()
            top = 3
            body_h = max(1, h - top - 2)
            if not items:
                stdscr.addnstr(top, 2, "(no files — use Tab→Save JSON copy on a notice)", w - 4)
                self._footer(stdscr, "Esc back")
                stdscr.refresh()
                if stdscr.getch() in (27,):
                    return
                continue
            sel = max(0, min(sel, len(items) - 1))
            start = max(0, sel - body_h + 1) if sel >= body_h else 0
            for i in range(start, min(len(items), start + body_h)):
                it = items[i]
                row = it.item
                line = f"{_clip(it.week, 8):8}  {_clip(_row_id(row), 18):18}  {_row_title(row)}"
                y = top + (i - start)
                if i == sel:
                    stdscr.attron(curses.A_REVERSE)
                    stdscr.addnstr(y, 1, _clip(line, w - 2), w - 2)
                    stdscr.attroff(curses.A_REVERSE)
                else:
                    stdscr.addnstr(y, 1, _clip(line, w - 2), w - 2)
            self._footer(stdscr, "↑↓  ↵ detail  Del/⌫ delete file  Esc back")
            stdscr.refresh()
            ch = stdscr.getch()
            if ch in (27,):
                return
            if ch in (curses.KEY_UP,):
                sel = max(0, sel - 1)
            elif ch in (curses.KEY_DOWN,):
                sel = min(len(items) - 1, sel + 1)
            elif ch in _ENTER:
                self._detail_screen(stdscr, rows[sel])
            elif _is_row_delete_ch(ch):
                try:
                    self.exports.delete(items[sel])
                    items.pop(sel)
                    rows.pop(sel)
                    if not items:
                        self._toast_set("Deleted")
                        return
                    sel = min(sel, len(items) - 1)
                    self._toast_set("Deleted file")
                except Exception as e:
                    self._toast_set(str(e))

    def _row_actions_menu(
        self,
        stdscr: "curses._CursesWindow",
        row: Dict[str, Any],
        *,
        browse_state: Optional[ListState] = None,
    ) -> None:
        opts: List[Tuple[str, str]] = [
            ("save_db", "Save to database (tracked list)"),
            ("export_json", "Save JSON copy to ~/.arrow/archive/…"),
            ("summarize", "Summarize notice (Ollama)…"),
            ("why_fit", "Why fit vs profile (Ollama)…"),
        ]
        if browse_state is not None and browse_state.rows:
            opts.append(("rank_list", "Rank this whole list by profile…"))
        opts.append(("back", "Back"))
        tag = self._menu_loop(
            stdscr,
            title="Actions",
            items=opts,
            footer_hint="↑↓  ↵ choose  Esc cancel",
        )
        if tag == "save_db":
            nid = _notice_id(row)
            if not nid:
                self._toast_set("No notice id")
                return
            try:
                self.repo.save_item(nid, source="tui")
                self._toast_set("Saved to database")
            except Exception as e:
                self._toast_set(str(e))
        elif tag == "export_json":
            try:
                payload = self._notice_payload(row)
                self.exports.append(payload)
                self._toast_set("Wrote JSON file under ~/.arrow/archive/")
            except Exception as e:
                self._toast_set(str(e))
        elif tag == "summarize":
            profile = load_company_profile()
            try:
                notice = self._notice_payload(row)
                parsed, _ = run_summarize_notice(profile, notice)
            except Exception as e:
                self._message_screen(stdscr, "Summarize failed", str(e))
                return
            if parsed:
                self._message_screen(
                    stdscr,
                    f"Summarize ({analysis_model_name()})",
                    json.dumps(parsed.model_dump(), indent=2, ensure_ascii=False),
                )
            else:
                self._message_screen(stdscr, "Summarize", "Invalid JSON from model. Try again or ollama ping.")
        elif tag == "why_fit":
            profile = load_company_profile()
            if not (
                str(profile.get("mission") or "").strip()
                or str(profile.get("notes") or "").strip()
                or profile.get("target_naics")
            ):
                self._message_screen(stdscr, "Profile", "Set mission/notes in Company profile menu first.")
                return
            try:
                notice = self._notice_payload(row)
                det = naive_deterministic_fit(profile, notice)
                parsed, raw = run_explain_rank(profile, notice)
            except Exception as e:
                self._message_screen(stdscr, "Why fit failed", str(e))
                return
            if parsed:
                body = json.dumps(parsed.model_dump(), indent=2, ensure_ascii=False)
                ft = float(det.get("total")) if det.get("total") is not None else 0.0
                body += f"\n\nHeuristic: fit={ft:.4f} (0–1) {det.get('components')}"
                self._message_screen(stdscr, f"Why fit ({analysis_model_name()})", body)
            else:
                fb = format_explain_rank_fallback(det)
                tail = (raw or "").strip()
                self._message_screen(stdscr, "Why fit (fallback)", f"{fb}\n\n---\n{tail}")
        elif tag == "rank_list":
            if browse_state is None:
                return
            profile = load_company_profile()
            if not (
                str(profile.get("mission") or "").strip()
                or str(profile.get("notes") or "").strip()
                or profile.get("target_naics")
            ):
                self._message_screen(
                    stdscr,
                    "Profile",
                    "Set mission, notes, or preferred NAICS first (Company profile menu).",
                )
                return
            ranked = rank_rows_by_profile(profile, list(browse_state.rows))
            browse_state.rows[:] = ranked
            browse_state.title = browse_state.title.split(" — ranked")[0] + " — ranked"
            self._toast_set("List re-ranked by profile")

    def _detail_screen(self, stdscr: "curses._CursesWindow", row: Dict[str, Any]) -> None:
        title = _row_title(row) or _row_id(row) or "Detail"
        base = without_fit_metadata(row)
        nid = _notice_id(base)
        full = self.repo.get_raw_dict(nid) if nid else None
        detail = dict(full if full is not None else base)
        text = json.dumps(detail, indent=2, ensure_ascii=False)
        raw_lines = text.splitlines()
        offset = 0
        while True:
            stdscr.erase()
            self._draw_brand(stdscr, _clip(title, 60))
            h, w = stdscr.getmaxyx()
            top = 3
            view_h = max(1, h - top - 2)
            wrap_w = max(1, w - 1)
            disp_lines = _wrap_json_lines_for_display(raw_lines, wrap_w)
            for i in range(view_h):
                idx = offset + i
                if idx >= len(disp_lines):
                    break
                stdscr.addnstr(top + i, 0, disp_lines[idx], wrap_w)
            self._footer(
                stdscr,
                "↑↓ PgUp/Dn scroll  Tab actions  Esc back",
            )
            stdscr.refresh()
            ch = stdscr.getch()
            if ch in (27,):
                return
            if ch == 9:
                self._row_actions_menu(stdscr, row, browse_state=None)
            elif ch in (curses.KEY_UP,):
                offset = max(0, offset - 1)
            elif ch in (curses.KEY_DOWN,):
                offset = min(max(0, len(disp_lines) - view_h), offset + 1)
            elif ch == curses.KEY_NPAGE:
                offset = min(max(0, len(disp_lines) - view_h), offset + view_h)
            elif ch == curses.KEY_PPAGE:
                offset = max(0, offset - view_h)

    def _status(self, stdscr: "curses._CursesWindow") -> None:
        n = self.repo.count_opportunities()
        r = self.repo.last_sync_run()
        lines = [f"Opportunities in DB: {n}", ""]
        if r:
            lines.append(
                f"Last sync #{r['id']}  {r['source_type']}  {r['status']}\n"
                f"seen={r['total_seen']}  new={r['new_count']}  changed={r['changed_count']}"
            )
            if r["finished_at"]:
                lines.append(f"Finished: {r['finished_at']}")
        else:
            lines.append("No sync runs yet. Use full CSV download or sync bulk auto (REPL).")
        self._message_screen(stdscr, "Status", "\n".join(lines))

    def _home(self, stdscr: "curses._CursesWindow") -> None:
        items: List[Tuple[str, str]] = [
            ("sync_bulk_auto", "Download official full CSV (SAM.gov) + ingest…"),
            ("sync_bulk", "Sync from local bulk CSV file…"),
            ("company_profile", "Company profile (for why fit / rank via Tab on a list)…"),
            ("list", "Browse recent from database…"),
            ("search_title", "Search title in database…"),
            ("search_id", "Search by notice ID / solicitation…"),
            ("saved_db", "Saved list (database)…"),
            ("exports", "JSON file copies on disk…"),
            ("changed", "Changed (multiple snapshots)…"),
            ("status", "Status"),
            ("quit", "Exit"),
        ]
        while True:
            tag = self._menu_loop(
                stdscr,
                title="main menu",
                items=items,
                footer_hint="↑↓  ↵ open  Esc exit",
            )
            if tag is None or tag == "quit":
                return
            if tag == "sync_bulk_auto":
                self._run_sync_bulk_auto(stdscr)
            elif tag == "sync_bulk":
                self._run_sync_bulk(stdscr)
            elif tag == "company_profile":
                self._run_company_profile(stdscr)
            elif tag == "list":
                n = self._pick_count(stdscr, db_total=self.repo.count_opportunities())
                if n:
                    rows = self.repo.list_recent(n)
                    self._browse_opportunities(stdscr, ListState(rows=rows, title=f"Recent ({n})", selected=0))
            elif tag == "search_title":
                q = self._read_line(stdscr, title="Search", prompt="Title contains:")
                if q:
                    rows = self.repo.search_title(q, limit=MAX_LIST_LIMIT)
                    self._browse_opportunities(stdscr, ListState(rows=rows, title=f"Search: {q}", selected=0))
            elif tag == "search_id":
                q = self._read_line(stdscr, title="Search", prompt="Notice ID or solicitation:")
                if q:
                    rows = self.repo.search_notice_id(q)
                    self._browse_opportunities(stdscr, ListState(rows=rows, title=f"ID: {q}", selected=0))
            elif tag == "saved_db":
                rows = self.repo.list_saved(MAX_LIST_LIMIT)

                def _rm(nid: str) -> bool:
                    return self.repo.remove_saved(nid)

                self._browse_opportunities(
                    stdscr,
                    ListState(rows=rows, title="Saved (database)", selected=0),
                    on_delete_notice=_rm,
                )
            elif tag == "exports":
                ex = list(self.exports.list_newest_first(500))
                self._browse_export_files(stdscr, ex)
            elif tag == "changed":
                rows = self.repo.list_changed_multi_snapshot(50)
                self._browse_opportunities(stdscr, ListState(rows=rows, title="Changed", selected=0))
            elif tag == "status":
                self._status(stdscr)

    def _app(self, stdscr: "curses._CursesWindow") -> None:
        curses.curs_set(0)
        stdscr.keypad(True)
        stdscr.nodelay(False)
        try:
            curses.start_color()
        except Exception:
            pass
        if self._initial_rows:
            self._browse_opportunities(
                stdscr,
                ListState(
                    rows=list(self._initial_rows),
                    title=self._initial_title or "From shell",
                    selected=0,
                ),
            )
        self._home(stdscr)


def main() -> None:
    enable_ipv4_preference()
    from arrow.env import load_dotenv_if_present

    load_dotenv_if_present()

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise RuntimeError("Arrow TUI requires a TTY (run it in a real terminal).")

    repo = OpportunityRepo()
    try:
        ArrowTui(repo).run()
    finally:
        try:
            repo.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
