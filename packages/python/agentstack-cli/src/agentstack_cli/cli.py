"""CLI entry point."""

from agentstack_cli import __version__


def main() -> None:
    print(f"agentstack v{__version__}")


if __name__ == "__main__":
    main()
