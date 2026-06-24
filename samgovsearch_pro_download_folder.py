from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, List
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from samgov_api_cache import SamGovApiCache
from samgovsearch_pro_zip_fast import SamGovSearchProZipFastApp


@dataclass
class DownloadFolderSettings:
    download_folder: str = ""
    open_folder_after_download: bool = True

    @classmethod
    def load(cls, path: Path) -> "DownloadFolderSettings":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return cls()
        if not isinstance(data, dict):
            return cls()
        return cls(
            download_folder=str(data.get("download_folder", "") or ""),
            open_folder_after_download=bool(data.get("open_folder_after_download", True)),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True), encoding="utf-8")


class SamGovSearchProDownloadFolderApp(SamGovSearchProZipFastApp):
    """Final user-facing app with prompt-free attachment downloads.

    Downloads go directly to the user's Downloads folder unless a custom folder
    is set ahead of time in Download Options. This avoids wasting seconds on a
    folder picker while SAM.gov's short-lived S3 ZIP URL is active.
    """

    def __init__(self) -> None:
        cache_root = SamGovApiCache.default().root
        self._download_settings_path = cache_root / "samgovsearch_download_settings.json"
        self.download_settings = DownloadFolderSettings.load(self._download_settings_path)
        self.download_folder_summary_var: tk.StringVar | None = None
        super().__init__()

    def _build_left_panel(self, left_panel: ttk.Frame) -> None:
        super()._build_left_panel(left_panel)
        self._add_download_options_section(left_panel, row=17)

    def _add_download_options_section(self, left_panel: ttk.Frame, row: int) -> None:
        frame = ttk.LabelFrame(left_panel, text="Download Options", padding=8)
        frame.grid(row=row, column=0, sticky="ew", pady=(8, 0))
        frame.columnconfigure(0, weight=1)

        self.download_folder_summary_var = tk.StringVar(value=self._download_folder_summary())
        ttk.Button(frame, text="Download Folder Options", command=self.open_download_options_dialog).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Label(
            frame,
            textvariable=self.download_folder_summary_var,
            wraplength=330,
        ).grid(row=1, column=0, sticky="w", pady=(5, 0))
        ttk.Label(
            frame,
            text="Attachment downloads do not ask for a folder during download. This prevents short-lived SAM.gov ZIP links from expiring while waiting for a prompt.",
            wraplength=330,
        ).grid(row=2, column=0, sticky="w", pady=(5, 0))

    def _download_folder_summary(self) -> str:
        configured = self.download_settings.download_folder.strip()
        root = self._download_root_folder()
        mode = "custom" if configured else "default Downloads"
        return f"Current folder ({mode}): {root}"

    def _default_download_folder(self) -> Path:
        downloads = Path.home() / "Downloads"
        return downloads if downloads.exists() else Path.home()

    def _download_root_folder(self) -> Path:
        configured = self.download_settings.download_folder.strip()
        if configured:
            return Path(configured).expanduser()
        return self._default_download_folder()

    def _ensure_download_root_folder(self) -> Path:
        root = self._download_root_folder()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def open_download_options_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Download Folder Options")
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.columnconfigure(0, weight=1)

        frame = ttk.Frame(dialog, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        folder_var = tk.StringVar(value=self.download_settings.download_folder.strip())
        open_after_var = tk.BooleanVar(value=self.download_settings.open_folder_after_download)

        ttk.Label(frame, text="Custom Download Folder").grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Entry(frame, textvariable=folder_var, width=58).grid(row=0, column=1, sticky="ew", pady=(0, 4))

        def browse() -> None:
            initial = folder_var.get().strip() or str(self._default_download_folder())
            selected = filedialog.askdirectory(title="Choose default SAM.gov download folder", initialdir=initial, parent=dialog)
            if selected:
                folder_var.set(selected)

        ttk.Button(frame, text="Browse", command=browse).grid(row=0, column=2, sticky="ew", padx=(6, 0), pady=(0, 4))

        ttk.Checkbutton(
            frame,
            text="Open folder after downloads finish",
            variable=open_after_var,
        ).grid(row=1, column=1, columnspan=2, sticky="w", pady=(0, 8))

        info = (
            "Leave this blank to use the normal Windows Downloads folder. The app saves immediately to this folder without showing a folder picker when you click Download Attachments."
        )
        ttk.Label(frame, text=info, wraplength=560).grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 10))

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, columnspan=3, sticky="ew")
        for column in range(5):
            buttons.columnconfigure(column, weight=1)

        def save() -> None:
            folder_text = folder_var.get().strip()
            if folder_text:
                try:
                    Path(folder_text).expanduser().mkdir(parents=True, exist_ok=True)
                except Exception as exc:
                    messagebox.showerror("Invalid Folder", f"Could not create or access the folder:\n\n{folder_text}\n\n{exc}", parent=dialog)
                    return
            self.download_settings = DownloadFolderSettings(
                download_folder=folder_text,
                open_folder_after_download=open_after_var.get(),
            )
            self.download_settings.save(self._download_settings_path)
            self._refresh_download_folder_summary()
            messagebox.showinfo("Download Options Saved", "Download folder options were saved.", parent=dialog)

        def use_downloads() -> None:
            folder_var.set("")

        def open_folder() -> None:
            try:
                os.startfile(str(self._ensure_download_root_folder()))  # type: ignore[attr-defined]
            except Exception as exc:
                messagebox.showerror("Open Folder Failed", str(exc), parent=dialog)

        ttk.Button(buttons, text="Save", command=save).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(buttons, text="Use Downloads", command=use_downloads).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(buttons, text="Open Folder", command=open_folder).grid(row=0, column=2, sticky="ew", padx=4)
        ttk.Button(buttons, text="Close", command=dialog.destroy).grid(row=0, column=3, columnspan=2, sticky="ew", padx=(4, 0))

        dialog.bind("<Return>", lambda _event: save())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.grab_set()

    def _refresh_download_folder_summary(self) -> None:
        var = getattr(self, "download_folder_summary_var", None)
        if var is not None:
            var.set(self._download_folder_summary())

    def download_selected_attachments(self) -> None:
        result = self._selected_result()
        if result is None:
            messagebox.showinfo("No Result Selected", "Select one result row before downloading attachments.")
            return

        try:
            root_folder = self._ensure_download_root_folder()
        except Exception as exc:
            messagebox.showerror("Download Folder Error", f"Could not create or access the download folder:\n\n{exc}")
            return

        target_folder = root_folder / self._safe_folder_name(
            getattr(result, "solicitation_number", "") or getattr(result, "notice_id", "") or getattr(result, "title", "") or "samgov_opportunity"
        )
        target_folder.mkdir(parents=True, exist_ok=True)

        notice_id = str(getattr(result, "notice_id", "") or "").strip()
        links = list(getattr(result, "resource_links", []) or [])
        zip_error = ""

        if notice_id:
            self.status_var_text.set("Trying SAM.gov Download All ZIP method...")
            self._log(f"Downloading attachments to: {target_folder}")
            self.update_idletasks()
            try:
                zip_path = self._download_samgov_website_zip(result, target_folder)
                self._log(f"Downloaded SAM.gov Download All ZIP: {zip_path}")
                self._open_download_folder_if_enabled(target_folder)
                messagebox.showinfo(
                    "Download Complete",
                    "Downloaded the SAM.gov Download All ZIP for the selected result.\n\n"
                    f"File:\n{zip_path}",
                )
                self.status_var_text.set("Downloaded SAM.gov Download All ZIP for selected result.")
                return
            except Exception as exc:
                zip_error = str(exc)
                self._log(f"SAM.gov Download All ZIP method unavailable: {zip_error}")

        if not links:
            detail = (
                "The selected result does not have known individual attachment links."
                if not zip_error else
                "The SAM.gov Download All ZIP method failed and the selected result does not have known individual attachment links."
            )
            if zip_error:
                detail += f"\n\nZIP method error:\n{zip_error}"
            messagebox.showinfo("No Attachments Found", detail)
            return

        attachment_names = self._attachment_names_for_result(result)
        saved_paths: List[Path] = []
        failures: List[str] = []

        self.status_var_text.set(f"Downloading {len(links)} individual attachment(s)...")
        self._log(f"Falling back to individual attachments in: {target_folder}")
        self.update_idletasks()

        for index, url in enumerate(links, start=1):
            name = self._attachment_name_for_index(attachment_names, index, url)
            target_path = self._unique_path(target_folder / self._safe_filename(name))

            try:
                final_path = self._download_attachment_url(
                    url=url,
                    target_path=target_path,
                    referer=getattr(result, "ui_link", "") or "https://sam.gov/",
                )
                saved_paths.append(final_path)
                self._log(f"Downloaded attachment {index}/{len(links)}: {final_path}")
            except Exception as exc:
                message = f"{name}: {exc}"
                failures.append(message)
                self._log(f"Attachment download failed: {message}")

        if saved_paths:
            self._open_download_folder_if_enabled(target_folder)

        summary = f"Downloaded {len(saved_paths)} of {len(links)} individual attachment(s).\n\nFolder:\n{target_folder}"
        if zip_error:
            summary += f"\n\nSAM.gov ZIP method was tried first but was unavailable:\n{zip_error}"
        if failures:
            summary += "\n\nFailures:\n" + "\n".join(failures[:8])
            if len(failures) > 8:
                summary += f"\n...and {len(failures) - 8} more."
            messagebox.showwarning("Download Complete With Errors", summary)
        else:
            messagebox.showinfo("Download Complete", summary)

        self.status_var_text.set(f"Downloaded {len(saved_paths)} individual attachment(s) for selected result.")

    def _open_download_folder_if_enabled(self, folder: Path) -> None:
        if not self.download_settings.open_folder_after_download:
            return
        try:
            os.startfile(str(folder))  # type: ignore[attr-defined]
        except Exception:
            pass


def main() -> None:
    app = SamGovSearchProDownloadFolderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
