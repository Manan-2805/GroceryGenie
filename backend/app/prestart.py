"""Compatibility entry point for existing images. Run migrations separately."""

import os
import sys


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Provide the ASGI server command. Run migrations separately.")
    os.execvp(sys.argv[1], sys.argv[1:])  # nosec B606


if __name__ == "__main__":
    main()
