import sys


def main() -> None:
    if "--tui" in sys.argv:
        sys.argv.remove("--tui")
        from sticky_notes.tui import main as tui_main

        tui_main()
    else:
        from sticky_notes.cli import main as cli_main

        cli_main()


if __name__ == "__main__":
    main()
