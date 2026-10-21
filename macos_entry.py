"""Native macOS entry point. Packaging never starts this application."""
import sys

if sys.platform != 'darwin':
    raise SystemExit('This entry point belongs to the macOS build.')

from macos_runtime import configure
configure()
import app
app.main()
