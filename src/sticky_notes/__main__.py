import sys


def main() -> None:  # pragma: no cover
    from sticky_notes.cli import main as cli_main

    cli_main(sys.argv[1:])


if __name__ == "__main__":  # pragma: no cover
    main()
