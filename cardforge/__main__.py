"""允许 `python -m cardforge <子命令>`。"""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
