"""Read-only comparison of local font CSS with official Google Fonts artifacts.

Network access is limited to fonts.googleapis.com and fonts.gstatic.com.
Writes no files. Redirect stdout only through the documented evidence workflow.
"""
import concurrent.futures
import argparse
import hashlib
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "product/app/design/vendor"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def fetch(url):
    if urllib.parse.urlparse(url).hostname not in {"fonts.googleapis.com", "fonts.gstatic.com"}:
        raise ValueError("Non-official host")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as response:
        return response.read()


def faces(css):
    result = []
    for body in re.findall(r"@font-face\s*\{([^}]+)\}", css):
        props = dict(re.findall(r"([\w-]+)\s*:\s*([^;]+);", body))
        url = re.search(r"url\(([^)]+)\)", props.get("src", ""))
        if url:
            result.append({"family": props["font-family"].strip("'\""),
                           "style": props["font-style"], "weight": props["font-weight"],
                           "unicode_range": props.get("unicode-range"), "url": url[1].strip("'\"")})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="Verify recorded local hashes without network")
    args = parser.parse_args()
    if args.offline:
        evidence = json.loads((BASE / "fonts/UPSTREAM-PROVENANCE.json").read_text())
        expected = {f["path"] for f in evidence["files"]}
        actual = {str(p.relative_to(ROOT)) for p in (BASE / "fonts").glob("*.woff2")}
        assert expected == actual, "Font inventory changed"
        for f in evidence["files"]:
            assert hashlib.sha256((ROOT / f["path"]).read_bytes()).hexdigest() == f["sha256"], f["path"]
            assert f["classification"] == "A" and f["upstream_matches"], f["path"]
            assert all(a["sha256"] == f["sha256"] for a in f["upstream_matches"])
        for n in evidence["license_notices"]:
            assert hashlib.sha256((ROOT / n["local_path"]).read_bytes()).hexdigest() == n["local_sha256"]
        for q in evidence["queries"]:
            assert hashlib.sha256(q["css"].encode()).hexdigest() == q["sha256"]
        print("PASS: 49 recorded font hashes, 7 license notices, official CSS digests; A=49 B=0 C=0")
        return
    local = []
    for name in ["fonts.css", "fonts-estandar.css", "fonts-sistema.css"]:
        for face in faces((BASE / name).read_text()):
            face["path"] = str((BASE / face.pop("url")).resolve().relative_to(ROOT))
            face["css"] = str((BASE / name).relative_to(ROOT))
            local.append(face)
    queries = []
    for family in sorted({f["family"] for f in local}):
        tuples = sorted({(int(f["style"] == "italic"), int(f["weight"])) for f in local if f["family"] == family})
        axis = "ital,wght@" + ";".join(f"{i},{w}" for i, w in tuples)
        query = "https://fonts.googleapis.com/css2?family=" + urllib.parse.quote(family + ":" + axis, safe=":,@;") + "&display=swap"
        css = fetch(query).decode()
        queries.append({"url": query, "user_agent": UA, "sha256": hashlib.sha256(css.encode()).hexdigest(), "css": css})
    # Newsreader local bytes retain both variable axes, including optical size.
    query = "https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,200..800&display=swap"
    css = fetch(query).decode()
    queries.append({"url": query, "user_agent": UA, "sha256": hashlib.sha256(css.encode()).hexdigest(), "css": css})
    upstream = [f for q in queries for f in faces(q["css"])]
    urls = sorted({f["url"] for f in upstream})
    def digest(url):
        data = fetch(url)
        return url, {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        artifacts = dict(pool.map(digest, urls))
    files = []
    for path in sorted({f["path"] for f in local}):
        declared = [f for f in local if f["path"] == path]
        data = (ROOT / path).read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        matches = [dict(f, **artifacts[f["url"]]) for f in upstream if artifacts[f["url"]]["sha256"] == sha]
        files.append({"path": path, "filename": Path(path).name, "sha256": sha, "bytes": len(data),
                      "local_css_faces": declared, "classification": "A" if matches else "C", "upstream_matches": matches,
                      "official_equivalent_candidates": [dict(f, **artifacts[f["url"]]) for f in upstream
                          if any(all(f[k] == d[k] for k in ["family", "weight", "style", "unicode_range"]) for d in declared)] if not matches else []})
    print(json.dumps({"schema_version": 1, "method": "SHA256 of official HTTPS artifact versus unchanged local bytes", "queries": queries, "files": files}, indent=2))


if __name__ == "__main__":
    main()
