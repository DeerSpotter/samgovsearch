from __future__ import annotations

from typing import Any, Dict

import samgovsearch as base
import samgovsearch_all_status as all_status
from samgov_api_cache import SamGovApiCache


class CachedSamGovSearchApp(all_status.SamGovSearchAllStatusApp):
    """Default API GUI with local query and notice caching enabled."""

    def __init__(self) -> None:
        self._api_cache = SamGovApiCache.default()
        self._cache_path_logged = False
        super().__init__()

    def _log_cache_path_once(self) -> None:
        if self._cache_path_logged:
            return
        self._cache_path_logged = True
        summary = self._api_cache.summary()
        self.queue.put((
            "log",
            "API cache folder: "
            f"{summary['cache_root']} "
            f"({summary['query_count']} cached querie(s), {summary['notice_count']} cached notice(s)).",
        ))

    def _search_sam_gov(
        self,
        client: base.SamGovClient,
        params: Dict[str, Any],
        settings: base.SearchSettings,
    ) -> Dict[str, Any]:
        self._log_cache_path_once()

        exact = self._api_cache.get_query_response(params)
        if exact is not None:
            self.queue.put(("log", "API cache hit: exact query reused, no SAM.gov request spent."))
            return exact

        notice = self._api_cache.get_notice_response(params)
        if notice is not None:
            self.queue.put(("log", "API cache hit: notice index reused, no SAM.gov request spent."))
            return notice

        self._wait_before_api_request(settings)
        if self.stop_event.is_set():
            return {"opportunitiesData": [], "totalRecords": 0}

        try:
            data = client.search(params)
        except RuntimeError as exc:
            message = str(exc)
            if "HTTP 429" in message or "throttled" in message.lower() or "quota" in message.lower():
                reset_text = self._extract_next_access_time(message)
                reset_suffix = f"\n\nSAM.gov next access time: {reset_text}" if reset_text else ""
                raise RuntimeError(
                    "SAM.gov quota or rate limit was reached. The search stopped so the app does not keep spending requests."
                    f"{reset_suffix}\n\n"
                    "Reduce the batch size, turn off Search all date ranges, lower broad keyword usage, "
                    "or wait until the reset time. Cached results remain available for future runs."
                ) from exc
            raise

        self._api_cache.store_query_response(params, data, source_label="api-search")
        item_count = len(data.get("opportunitiesData") or []) if isinstance(data, dict) else 0
        self.queue.put(("log", f"API cache stored: network response with {item_count} item(s)."))
        return data


def main() -> None:
    app = CachedSamGovSearchApp()
    app.mainloop()


if __name__ == "__main__":
    main()
