"""Entry point for the Road to Vostok Save Game Syncer."""

import sys


def main() -> None:
    from .gui import SyncerApp
    app = SyncerApp()
    app.run()


if __name__ == "__main__":
    main()
