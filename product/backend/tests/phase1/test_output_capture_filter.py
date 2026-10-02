"""
test_output_capture_filter — #5: el capture de obra excluye ruido VCS/cache/build cuando el
workdir es un repo, y conserva los artefactos reales. Sintético (no depende de run_outputs).
"""
from pathlib import Path

from app.phase1.output_capture_filter import captured_files, is_noise


def _touch(p: Path, content: str = "x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def test_filtra_ruido_conserva_obra(tmp_path: Path):
    # obra real
    _touch(tmp_path / "FIX.md", "# fix")
    _touch(tmp_path / "mathlib.py", "def add(a,b): return a+b")
    _touch(tmp_path / "report.txt", "resultado")
    _touch(tmp_path / "src" / "util.py", "x=1")          # subdir real, NO ruido
    # ruido: repo git, caches, build, deps, metadata SO
    _touch(tmp_path / ".git" / "HEAD", "ref: refs/heads/main")
    _touch(tmp_path / ".git" / "objects" / "ab" / "cdef", "blob")
    _touch(tmp_path / "__pycache__" / "mathlib.cpython-313.pyc", "bytecode")
    _touch(tmp_path / "src" / "__pycache__" / "util.cpython-313.pyc", "bytecode")
    _touch(tmp_path / ".pytest_cache" / "v" / "cache" / "lastfailed", "{}")
    _touch(tmp_path / "node_modules" / "left-pad" / "index.js", "module")
    _touch(tmp_path / ".DS_Store", "macos")
    _touch(tmp_path / "build" / "out.o", "obj")

    names = {p.relative_to(tmp_path).as_posix() for p in captured_files(tmp_path)}
    assert names == {"FIX.md", "mathlib.py", "report.txt", "src/util.py"}


def test_salta_cero_bytes(tmp_path: Path):
    _touch(tmp_path / "real.txt", "data")
    (tmp_path / "empty.txt").write_text("")            # 0 bytes → fuera
    names = {p.name for p in captured_files(tmp_path)}
    assert names == {"real.txt"}


def test_is_noise_unitario():
    assert is_noise(Path(".git/HEAD"))
    assert is_noise(Path("a/__pycache__/x.pyc"))
    assert is_noise(Path("pkg.egg-info/PKG-INFO"))
    assert is_noise(Path(".DS_Store"))
    assert is_noise(Path("x.pyc"))
    assert not is_noise(Path("FIX.md"))
    assert not is_noise(Path("src/util.py"))
    assert not is_noise(Path("data/report.txt"))


def test_workdir_inexistente(tmp_path: Path):
    assert captured_files(tmp_path / "no-existe") == []
