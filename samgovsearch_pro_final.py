from __future__ import annotations

from typing import Any, List

from samgovsearch_pro import SamGovSearchProApp


class SamGovSearchProFinalApp(SamGovSearchProApp):
    """Final launcher target for the pro UI.

    Keeps attachment-name filtering active during table rebuilds, sorting,
    clearing filters, and cached-result searches.
    """

    def _display_results(self) -> List[Any]:
        if not getattr(self, "_active_result_filter", "") and not getattr(self, "_attachment_name_filter_text", ""):
            return list(self.results)
        return [
            result
            for result in self.results
            if self._result_matches_filter(result, self._active_result_filter)
        ]


def main() -> None:
    app = SamGovSearchProFinalApp()
    app.mainloop()


if __name__ == "__main__":
    main()
