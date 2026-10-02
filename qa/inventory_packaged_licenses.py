#!/usr/bin/env python3
"""Inventory distribution metadata and bundled JS licenses from an exact .app."""
from __future__ import annotations

import argparse
import csv
import email
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    app = args.app.resolve()
    resources = app / "Contents/Resources"
    assert (app / "Contents/Info.plist").is_file()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    python_rows = []
    for path in sorted(app.rglob("METADATA")):
        if not path.parent.name.endswith(".dist-info"):
            continue
        meta = email.message_from_string(path.read_text(encoding="utf-8", errors="replace"))
        name = meta.get("Name", path.parent.name)
        version = meta.get("Version", "UNKNOWN")
        expressions = [meta.get("License-Expression", "").strip()]
        license_text = meta.get("License", "").strip()
        if license_text and len(license_text) < 200 and "\n" not in license_text:
            expressions.append(license_text)
        expressions.extend(value.split(" :: ")[-1] for value in meta.get_all("Classifier", [])
                           if value.startswith("License ::"))
        files = sorted(str(file.relative_to(app)) for file in path.parent.rglob("*")
                       if file.is_file() and ("license" in file.name.lower() or
                                              file.name.lower().startswith("copying") or
                                              file.name.lower() == "notice"))
        project = meta.get("Home-page", "")
        if not project:
            for value in meta.get_all("Project-URL", []):
                if ", " in value:
                    project = value.split(", ", 1)[1]
                    break
        python_rows.append({
            "component": name, "version": version, "upstream": project,
            "license_declaration": " | ".join(dict.fromkeys(x for x in expressions if x)) or "SEE_SHIPPED_LICENSE_TEXT",
            "license_text_files": "; ".join(files),
            "metadata_in_app": str(path.relative_to(app)),
        })
    with (output / "PYTHON_DISTRIBUTIONS.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=python_rows[0].keys())
        writer.writeheader()
        writer.writerows(python_rows)

    manifest_path = resources / "product/app/design/sala-v2/vendor/assistant-ui.bundle.manifest.json"
    manifest = json.loads(manifest_path.read_text())
    npm_rows = [
        {"component": name, "version": item["version"], "license": item["license"],
         "evidence_in_app": str(manifest_path.relative_to(app))}
        for name, item in sorted(manifest["npm_embebido"].items())
    ]
    with (output / "NPM_EMBEDDED.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=npm_rows[0].keys())
        writer.writeheader()
        writer.writerows(npm_rows)

    node_rows = []
    for path in sorted(app.rglob("package.json")):
        parts = path.parts
        if "node_modules" not in parts:
            continue
        index = max(i for i, part in enumerate(parts) if part == "node_modules")
        suffix = parts[index + 1:-1]
        # Nested package.json files under dist/, esm/, etc. inherit their root
        # package's license and are not separate dependency distributions.
        if not (len(suffix) == 1 or len(suffix) == 2 and suffix[0].startswith("@")):
            continue
        package = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        license_value = package.get("license", "")
        if isinstance(license_value, dict):
            license_value = license_value.get("type", "")
        license_files = sorted(str(file.relative_to(app)) for file in path.parent.iterdir()
                               if file.is_file() and ("license" in file.name.lower() or
                                                      "copying" in file.name.lower()))
        node_rows.append({
            "component": package.get("name", path.parent.name),
            "version": package.get("version", "UNKNOWN"),
            "upstream": package.get("repository", "") if isinstance(package.get("repository"), str)
            else package.get("repository", {}).get("url", ""),
            "license_declaration": str(license_value),
            "local_license_text_files": "; ".join(license_files),
            "package_json_in_app": str(path.relative_to(app)),
        })
    with (output / "NODE_MODULES.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=node_rows[0].keys())
        writer.writeheader()
        writer.writerows(node_rows)

    matrix_path = resources / "THIRD-PARTY-NOTICES/THIRD-PARTY-MATRIX.json"
    matrix = json.loads(matrix_path.read_text())
    missing_notices = [notice for notice in matrix["notice_files"]
                       if not (resources / "THIRD-PARTY-NOTICES" / notice).is_file()]
    assert not missing_notices, missing_notices
    print(f"python_metadata={len(python_rows)} unique_name_versions={len(set((r['component'].lower(), r['version']) for r in python_rows))}")
    print(f"npm_embedded={len(npm_rows)} notice_files={len(matrix['notice_files'])} missing_notices=0")
    missing_license = [row for row in node_rows if not row["license_declaration"]]
    missing_text = [row for row in node_rows if not row["local_license_text_files"]]
    print(f"node_packages={len(node_rows)} unique_name_versions={len(set((r['component'], r['version']) for r in node_rows))}")
    print(f"node_missing_license_declaration={len(missing_license)} node_missing_local_license_text={len(missing_text)}")


if __name__ == "__main__":
    main()
