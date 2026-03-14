# nuitka-project-if: {OS} in ("Windows"):
#   nuitka-project: --output-filename=nxbt.exe
# nuitka-project-else:
#   nuitka-project: --output-filename=nxbt

# nuitka-project: --mode=onefile
# nuitka-project: --file-version=0.1.0
# nuitka-project: --product-version=0.1.0
# nuitka-project: --output-dir=release
# nuitka-project: --include-data-dir=./nxbt/web/static=nxbt/web/static
# nuitka-project: --include-data-dir=./nxbt/web/templates=nxbt/web/templates
# nuitka-project: --include-data-dir=./nxbt/controller/sdp=nxbt/controller/sdp
# nuitka-project: --remove-output

import sys
from pathlib import Path


if __package__ in (None, ""):
    package_dir = Path(__file__).resolve().parent
    project_root = str(package_dir.parent)
    package_dir_str = str(package_dir)

    if sys.path and sys.path[0] == package_dir_str:
        sys.path.pop(0)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from nxbt.cli import main

main()
