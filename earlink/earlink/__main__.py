import sys

if sys.platform == "win32":
    from .windows_ui import main
else:
    from .ui import main

raise SystemExit(main())
