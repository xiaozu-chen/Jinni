"""Start Jinni in the CLI or as a local web API."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Jinni.")
    parser.add_argument(
        "--run-as",
        choices=("cli", "web"),
        default="cli",
        help="run the command-line interface or the local web API (default: cli)",
    )
    args, remaining = parser.parse_known_args()

    if args.run_as == "cli":
        from interface.cli.jinni import main as run_cli

        run_cli(remaining)
        return

    if remaining:
        parser.error(f"unrecognized arguments for web mode: {' '.join(remaining)}")

    import uvicorn

    uvicorn.run("interface.web.api:app", host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()