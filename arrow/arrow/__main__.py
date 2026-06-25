import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1].lower() in ("tui", "ui"):
        from arrow.tui import main as tui_main

        tui_main()
        return
    from arrow.repl import main as repl_main

    repl_main()


if __name__ == "__main__":
    main()
