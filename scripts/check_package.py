"""check_package.py — 打包完整性门禁

构建 wheel 并确认全部机型知识库 YAML 都被打进包里。
v2.3.0 曾因 package-data glob 不递归导致 wheel 里 0 个 YAML —— pip 安装即废。
这个门禁防止该问题回归。

用法: python3 scripts/check_package.py   (退出码 0=通过, 1=失败)
依赖: pip install build
"""
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    expected = sorted(
        p.relative_to(ROOT / "tools").as_posix()
        for p in (ROOT / "tools" / "knowledge").rglob("*.yaml")
    )
    if not expected:
        print("❌ 仓库里找不到任何知识库 YAML (tools/knowledge/**/*.yaml)")
        return 1

    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", td, str(ROOT)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print("❌ wheel 构建失败:")
            print(r.stderr[-2000:])
            return 1
        wheel = next(Path(td).glob("*.whl"))
        names = zipfile.ZipFile(wheel).namelist()
        packed = sorted(
            n[len("tools/"):] for n in names
            if n.startswith("tools/knowledge/") and n.endswith(".yaml")
        )

    missing = [f for f in expected if f not in packed]
    print(f"仓库知识库 YAML: {len(expected)} | wheel 内: {len(packed)}")
    if missing:
        print(f"❌ wheel 缺失 {len(missing)} 个知识库文件:")
        for f in missing[:10]:
            print(f"   - {f}")
        return 1
    print(f"✅ 打包完整性通过 ({wheel.name}, {len(packed)} 个 YAML)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
