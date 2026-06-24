from __future__ import annotations

import json
import os
import re
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, List, Optional
from xml.etree import ElementTree as ET
import tkinter as tk
from tkinter import messagebox, ttk

from samgovsearch_pro_predefined_naics_fixed import SamGovSearchProPredefinedNaicsFixedApp


CENSUS_2022_NAICS_XLSX_URL = "https://www.census.gov/naics/2022NAICS/2022_NAICS_Structure.xlsx"
NAICS_CACHE_FILE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SAMGovSearch" / "naics_2022_cache.json"
DEFAULT_INTERESTED_NAICS_NUMBERS = "336414\n336415\n336419"
FALLBACK_KNOWN_NAICS = {
    "336414": "Guided Missile and Space Vehicle Manufacturing",
    "336415": "Guided Missile and Space Vehicle Propulsion Unit and Propulsion Unit Parts Manufacturing",
    "336419": "Other Guided Missile and Space Vehicle Parts and Auxiliary Equipment Manufacturing",
}


class CensusNaicsLookup:
    """Loads 2022 NAICS code/title data from the official Census XLSX reference file.

    Uses only the Python standard library. The parsed lookup is cached under
    LOCALAPPDATA so validation does not re-download the XLSX every launch.
    """

    def __init__(self, cache_file: Path = NAICS_CACHE_FILE) -> None:
        self.cache_file = cache_file
        self._codes: Optional[Dict[str, str]] = None
        self.source_note = "not loaded"

    def codes(self) -> Dict[str, str]:
        if self._codes is not None:
            return self._codes

        cached = self._read_cache()
        if cached:
            self._codes = cached
            self.source_note = f"cached Census 2022 NAICS reference: {self.cache_file}"
            return self._codes

        try:
            loaded = self._download_and_parse()
        except Exception:
            loaded = dict(FALLBACK_KNOWN_NAICS)
            self.source_note = "embedded fallback for default missile NAICS codes"
        self._codes = loaded
        return self._codes

    def title_for(self, code: str) -> Optional[str]:
        return self.codes().get(code)

    def _read_cache(self) -> Dict[str, str]:
        try:
            if not self.cache_file.exists():
                return {}
            with self.cache_file.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            codes = data.get("codes") if isinstance(data, dict) else None
            if isinstance(codes, dict):
                return {str(k): str(v) for k, v in codes.items() if re.fullmatch(r"\d{2,6}", str(k))}
        except Exception:
            return {}
        return {}

    def _write_cache(self, codes: Dict[str, str]) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_file.open("w", encoding="utf-8") as handle:
                json.dump({"source": CENSUS_2022_NAICS_XLSX_URL, "codes": codes}, handle, indent=2, sort_keys=True)
        except Exception:
            pass

    def _download_and_parse(self) -> Dict[str, str]:
        request = urllib.request.Request(
            CENSUS_2022_NAICS_XLSX_URL,
            headers={"User-Agent": "samgovsearch/naics-validator"},
        )
        with urllib.request.urlopen(request, timeout=25) as response:
            blob = response.read()

        codes = self._parse_xlsx_bytes(blob)
        if not codes:
            raise RuntimeError("No NAICS codes found in Census reference file.")
        self._write_cache(codes)
        self.source_note = f"downloaded official Census 2022 NAICS reference: {CENSUS_2022_NAICS_XLSX_URL}"
        return codes

    def _parse_xlsx_bytes(self, blob: bytes) -> Dict[str, str]:
        ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        with zipfile.ZipFile(__import__("io").BytesIO(blob)) as archive:
            shared_strings = self._read_shared_strings(archive, ns)
            sheet_name = self._first_sheet_name(archive)
            if not sheet_name:
                return {}
            root = ET.fromstring(archive.read(sheet_name))

        rows: List[List[str]] = []
        for row in root.findall(".//a:sheetData/a:row", ns):
            values: List[str] = []
            for cell in row.findall("a:c", ns):
                ref = cell.attrib.get("r", "")
                col_index = self._column_index(ref)
                while len(values) <= col_index:
                    values.append("")
                values[col_index] = self._cell_text(cell, shared_strings, ns)
            if any(value.strip() for value in values):
                rows.append(values)

        code_col = 0
        title_col = 1
        for row in rows[:20]:
            lowered = [value.lower() for value in row]
            for idx, value in enumerate(lowered):
                if "code" in value and "naics" in value:
                    code_col = idx
                if "title" in value or "description" in value:
                    title_col = idx

        codes: Dict[str, str] = {}
        for row in rows:
            if len(row) <= code_col:
                continue
            code_match = re.fullmatch(r"\d{2,6}", row[code_col].strip())
            if not code_match:
                continue
            title = row[title_col].strip() if len(row) > title_col else ""
            codes[code_match.group(0)] = title
        return codes

    def _read_shared_strings(self, archive: zipfile.ZipFile, ns: Dict[str, str]) -> List[str]:
        try:
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        except KeyError:
            return []
        strings: List[str] = []
        for item in root.findall("a:si", ns):
            text_parts = [node.text or "" for node in item.findall(".//a:t", ns)]
            strings.append("".join(text_parts))
        return strings

    def _first_sheet_name(self, archive: zipfile.ZipFile) -> str:
        for name in archive.namelist():
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                return name
        return ""

    def _column_index(self, ref: str) -> int:
        letters = "".join(ch for ch in ref if ch.isalpha()).upper()
        value = 0
        for ch in letters:
            value = value * 26 + (ord(ch) - ord("A") + 1)
        return max(0, value - 1)

    def _cell_text(self, cell: ET.Element, shared_strings: List[str], ns: Dict[str, str]) -> str:
        value_node = cell.find("a:v", ns)
        if value_node is None or value_node.text is None:
            inline = cell.find(".//a:t", ns)
            return inline.text if inline is not None and inline.text else ""
        value = value_node.text.strip()
        if cell.attrib.get("t") == "s":
            try:
                return shared_strings[int(value)]
            except Exception:
                return ""
        return value


class SamGovSearchProNaicsValidatedApp(SamGovSearchProPredefinedNaicsFixedApp):
    """Final launcher target: number-only NAICS list with Census validation."""

    def __init__(self) -> None:
        self._naics_lookup = CensusNaicsLookup()
        super().__init__()

    def _add_interested_naics_section(self, left_panel: ttk.Frame, row: int) -> None:
        frame = ttk.LabelFrame(left_panel, text="Interested NAICS Numbers", padding=8)
        frame.grid(row=row, column=0, sticky="ew", pady=(8, 0))
        frame.columnconfigure(0, weight=1)

        ttk.Label(
            frame,
            text="Numbers only. One 6 digit NAICS code per line.",
            wraplength=330,
        ).grid(row=0, column=0, sticky="w")

        self.naics_text = tk.Text(frame, width=36, height=4, wrap="none")
        self.naics_text.grid(row=1, column=0, sticky="ew", pady=(4, 4))
        self.naics_text.insert("1.0", DEFAULT_INTERESTED_NAICS_NUMBERS)

        ttk.Button(
            frame,
            text="Verify NAICS Codes",
            command=self._show_naics_verification,
        ).grid(row=2, column=0, sticky="ew", pady=(4, 4))

        ttk.Label(
            frame,
            text=(
                "Validation uses the official U.S. Census 2022 NAICS Structure reference file when available, "
                "then caches it locally."
            ),
            wraplength=330,
        ).grid(row=3, column=0, sticky="w", pady=(4, 0))

    def _interested_naics_codes(self) -> List[str]:
        widget = getattr(self, "naics_text", None)
        raw = widget.get("1.0", "end") if widget is not None else DEFAULT_INTERESTED_NAICS_NUMBERS
        codes: List[str] = []
        seen = set()
        bad_lines: List[str] = []

        for line_number, line in enumerate(raw.splitlines(), start=1):
            text = line.strip()
            if not text:
                continue
            if not re.fullmatch(r"\d{6}", text):
                bad_lines.append(f"line {line_number}: {text!r}")
                continue
            if text not in seen:
                seen.add(text)
                codes.append(text)

        if bad_lines:
            raise ValueError(
                "Interested NAICS Numbers must be numbers only, one 6 digit code per line.\n\n"
                + "\n".join(bad_lines)
            )
        return codes

    def _read_settings(self):
        settings = super()._read_settings()
        if getattr(settings, "use_predefined_naics", False):
            self._validate_naics_codes(getattr(settings, "predefined_naics_codes", []) or [])
        return settings

    def _validate_naics_codes(self, codes: List[str]) -> Dict[str, str]:
        lookup = self._naics_lookup
        titles = lookup.codes()
        invalid = [code for code in codes if code not in titles]
        if invalid:
            raise ValueError(
                "These NAICS codes were not found in the 2022 NAICS reference data: "
                + ", ".join(invalid)
                + "\n\nUse one valid 6 digit NAICS code per line."
            )
        return {code: titles.get(code, "") for code in codes}

    def _show_naics_verification(self) -> None:
        try:
            codes = self._interested_naics_codes()
            verified = self._validate_naics_codes(codes)
        except Exception as exc:
            messagebox.showerror("NAICS Validation Failed", str(exc), parent=self)
            return

        lines = [f"{code} = {title}" for code, title in verified.items()]
        lines.append("")
        lines.append(f"Source: {self._naics_lookup.source_note}")
        messagebox.showinfo("NAICS Codes Verified", "\n".join(lines), parent=self)


def main() -> None:
    app = SamGovSearchProNaicsValidatedApp()
    app.mainloop()


if __name__ == "__main__":
    main()
