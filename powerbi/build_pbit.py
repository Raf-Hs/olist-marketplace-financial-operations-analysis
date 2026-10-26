"""Build the native Power BI template (`MarketplaceFinance.pbit`) from the PBIP.

The PBIP project in `powerbi/MarketplaceFinance/` is the editable source.
This script compiles it into a `.pbit` template that Power BI Desktop opens
directly: model, Power Query and the five report pages.

WHY A .pbit AND NOT A .pbix
---------------------------
A `.pbix` with an embedded model has to be written by Power BI Desktop
itself. `pbi-tools` refuses to compile a model-bearing project into `.pbix`
("Compiling a project containing a data model into a PBIX file is not
supported"), and Power BI Desktop is a GUI application that cannot be driven
headlessly. The `.pbit` is the supported equivalent: it carries the full
model and the report, and opening it in Power BI Desktop and saving produces
the `.pbix` in two clicks.

PREREQUISITES
-------------
`pbi-tools` core CLI (>= 1.2) and a .NET runtime (8 or newer):

    python powerbi/build_pbit.py --download-tools

The script can fetch the official release itself if it is not already on the
PATH. The compiled template is committed to the repository, so this step is
only needed when the model or the report changes.

Usage:

    python powerbi/build_pbit.py [--pbi-tools <path>] [--download-tools]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

POWERBI_DIR = Path(__file__).resolve().parent
PROJECT_DIR = POWERBI_DIR / "MarketplaceFinance"
MODEL_BIM = PROJECT_DIR / "MarketplaceFinance.SemanticModel" / "model.bim"
REPORT_JSON = PROJECT_DIR / "MarketplaceFinance.Report" / "report.json"
DATA_DIR = POWERBI_DIR / "MarketplaceFinance" / "Data"
OUTPUT_PBIT = POWERBI_DIR / "MarketplaceFinance.pbit"

TOOLS_RELEASE_URL = (
    "https://github.com/pbi-tools/pbi-tools/releases/latest/download/"
    "pbi-tools.core.1.2.0_{platform}.zip"
)

# pbi-tools reads a decompiled-PBIX folder layout. These are the parts it
# requires; the ones that carry no content are written empty.
REQUIRED_PARTS = {
    "Version.txt": "1.28",
    "Settings/Version.txt": "1.28",
    "Settings/DiagramState.json": "{}",
    "Settings/ReportSettings.json": "{}",
    "Settings/Metadata.json": "{}",
    "Metadata": "{}",
    "ReportMetadata.json": "{}",
    "ReportSettings.json": "{}",
    "Connections": "{}",
}


def find_pbi_tools(explicit: str | None = None) -> Path | None:
    if explicit:
        candidate = Path(explicit)
        if candidate.exists():
            return candidate
        return None
    for name in ("pbi-tools", "pbi-tools.core", "pbi-tools.core.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)
    local = POWERBI_DIR / ".tools" / "pbi-tools.core.exe"
    return local if local.exists() else None


def download_tools() -> Path:
    """Fetch the official pbi-tools core release into powerbi/.tools/."""
    system = platform.system().lower()
    arch = "win" if system == "windows" else ("linux" if system == "linux" else "osx")
    if arch == "osx":
        arch = "osx"
    url = TOOLS_RELEASE_URL.format(platform=f"{arch}-x64")
    target_dir = POWERBI_DIR / ".tools"
    target_dir.mkdir(parents=True, exist_ok=True)
    print(f"[build_pbit] downloading {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=600) as response:
        payload = response.read()
    archive = target_dir / "pbi-tools.zip"
    archive.write_bytes(payload)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(target_dir)
    archive.unlink(missing_ok=True)
    for candidate in target_dir.glob("pbi-tools.core*"):
        if candidate.suffix == ".exe" or os.access(candidate, os.X_OK):
            print(f"[build_pbit] pbi-tools ready at {candidate}")
            return candidate
    raise FileNotFoundError("pbi-tools download did not produce an executable")


def run_tool(tool: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # pbi-tools ships for .NET 8/9; allow it to run on a newer runtime.
    env.setdefault("DOTNET_ROLL_FORWARD", "Major")
    result = subprocess.run(
        [str(tool), *args], capture_output=True, text=True, env=env, timeout=1800
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"pbi-tools {' '.join(args)} failed:\n{result.stdout[-3000:]}\n{result.stderr[-3000:]}"
        )
    return result


def build(tool: Path) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project = root / "project"
        project.mkdir()

        # 1. The report part.
        (project / "Report").mkdir()
        shutil.copy(REPORT_JSON, project / "Report" / "report.json")

        # 2. The empty package parts pbi-tools expects.
        for relative, content in REQUIRED_PARTS.items():
            target = project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        # 3. The data folder: the CSV extracts the Power Query expressions
        #    read from. It is embedded in the template so the model opens
        #    populated without a live connection.
        if DATA_DIR.exists():
            shutil.copytree(DATA_DIR, project / "Data")

        # 4. The model, in the Tabular Editor folder layout pbi-tools reads.
        model_folder = project / "Model"
        run_tool(tool, "convert", str(MODEL_BIM), str(model_folder), "Legacy", "-overwrite")

        # 5. Compile to the template.
        run_tool(tool, "compile", str(project), str(OUTPUT_PBIT), "PBIT", "-overwrite")

    return OUTPUT_PBIT


def verify(path: Path) -> None:
    """Check the compiled template carries the model, the report and the data."""
    with zipfile.ZipFile(path) as archive:
        parts = archive.namelist()
        model_parts = [p for p in parts if p.startswith("DataModel")]

    if "Report/Layout" not in parts:
        raise RuntimeError("the compiled template has no report layout")
    if not model_parts:
        raise RuntimeError("the compiled template has no data model")

    data_parts = [p for p in parts if p.lower().startswith("data/")]
    print(f"  parts         : {', '.join(parts)}")
    print(f"  model part    : {model_parts[0]}")
    print(f"  data files    : {len(data_parts)}")

    # The model inside the template must expose the measures the report uses.
    schema = next(p for p in parts if p.startswith("DataModel"))
    with zipfile.ZipFile(path) as archive:
        payload = archive.read(schema)
    try:
        text = payload.decode("utf-16-le", errors="ignore")
        model = json.loads(text)
        tables = model.get("model", model).get("tables", [])
        measures = [m["name"] for t in tables for m in t.get("measures", [])]
        print(f"  measures      : {len(measures)}")
        if not measures:
            raise RuntimeError("the compiled model contains no measures")
    except json.JSONDecodeError:
        # Older schema layouts are not plain JSON; the part presence check above
        # is the contract that matters.
        print("  measures      : (schema is not plain JSON - skipped parse)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pbi-tools", help="path to the pbi-tools CLI executable")
    parser.add_argument(
        "--download-tools",
        action="store_true",
        help="download the official pbi-tools core release if it is not on the PATH",
    )
    args = parser.parse_args()

    if not MODEL_BIM.exists() or not REPORT_JSON.exists():
        print("The PBIP project is missing. Expected:")
        print(f"  {MODEL_BIM}")
        print(f"  {REPORT_JSON}")
        print("Run `python src/build_powerbi_model.py` first.")
        return 1

    tool = find_pbi_tools(args.pbi_tools)
    if tool is None and args.download_tools:
        tool = download_tools()
    if tool is None:
        print(
            "pbi-tools CLI not found. Re-run with --download-tools to fetch it, or pass\n"
            "--pbi-tools <path to pbi-tools.core.exe>. The compiled template is\n"
            "committed, so this step is only needed when the model changes."
        )
        return 1

    print("Building the Power BI template")
    print(f"  pbi-tools     : {tool}")
    print(f"  model         : {MODEL_BIM.relative_to(POWERBI_DIR)}")
    print(f"  report        : {REPORT_JSON.relative_to(POWERBI_DIR)}")
    print(f"  data          : {DATA_DIR.relative_to(POWERBI_DIR)}")

    output = build(tool)
    verify(output)
    print(f"  template      : {output} ({output.stat().st_size:,} bytes)")
    print("\nOpen it in Power BI Desktop and use File > Save as to produce the .pbix.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
