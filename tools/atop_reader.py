"""
atop_reader — atop 系统监控解析 (源自 roboonto 项目, 见 SOURCES.md)
====================================

读 atop 系统监控 binary 文件,导出系统状态时序。

atop 是 Linux 的系统级性能记录器,默认 60s 一帧,记录:
- CPU 总体 / 各核
- 内存 / swap
- 磁盘 IO
- 网络 IO
- 进程级 CPU/MEM/IO

依赖:
    系统装 `atop` 命令(macOS 通常没有,需要在产生 atop 文件的机器或 Linux 容器里跑)
    通过 subprocess 调 `atop -r <file> -P <label>` 解析

输出:dict 形式的时序数据,可对齐 mcap 时间戳
"""

from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Iterator, Optional


# atop 的 -P parseable 输出 label 列表(只取关键的几个)
ATOP_LABELS = {
    "CPU": "CPU 整机",
    "MEM": "内存",
    "SWP": "swap",
    "DSK": "磁盘 IO",
    "NET": "网络 IO",
    "PRC": "进程数",
}


class AtopReader:
    """读 atop binary 文件,导出系统时序。"""

    def __init__(self, atop_binary: str = "atop"):
        self.atop_binary = atop_binary
        self.frames_read = 0
        self.errors: list[str] = []
        self._use_wsl: bool = False

    def is_atop_available(self) -> bool:
        """检测系统是否装了 atop 命令。Windows 上通过 WSL 调用。"""
        # 先试原生
        try:
            subprocess.run(
                [self.atop_binary, "-V"],
                capture_output=True, timeout=5
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Windows 上试 WSL
        try:
            r = subprocess.run(
                ["wsl", self.atop_binary, "-V"],
                capture_output=True, timeout=10
            )
            if r.returncode == 0:
                self._use_wsl = True
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return False

    def _run_atop(self, args: list[str], timeout: int = 30, binary: str | None = None) -> subprocess.CompletedProcess:
        """运行 atop 相关命令,自动选择原生或 WSL。
        WSL 模式通过 bash -c + MSYS_NO_PATHCONV 前缀解决路径转换。"""
        if self._use_wsl:
            bin_part = self.atop_binary if binary is None else ("" if binary == "" else binary)
            if binary == "":
                cmd = " ".join(f'"{a}"' for a in ["wsl", "--"] + args)
            else:
                cmd = " ".join(f'"{a}"' for a in ["wsl", "--", bin_part] + args)
            r = subprocess.run(
                ["bash", "-c", f'MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*" {cmd}'],
                capture_output=True, timeout=timeout
            )
        else:
            r = subprocess.run([self.atop_binary] + args, capture_output=True, timeout=timeout)
        r.stdout_str = r.stdout.decode("utf-8", errors="replace") if r.stdout else ""
        r.stderr_str = r.stderr.decode("utf-8", errors="replace") if r.stderr else ""
        return r

    def read_summary(self, atop_path: Path) -> dict:
        """读一个 atop 文件,产出汇总(峰值 / 均值 / 异常帧)。
        自动处理版本兼容: 如果格式不兼容, 用 atopconvert 转换后读取。"""
        if not self.is_atop_available():
            return {
                "error": "atop binary not available on this system",
                "hint": "atop 文件需要在 Linux 系统(产生它的那台机器)上解析",
                "file": str(atop_path),
            }

        # Windows WSL 路径转换: D:\foo\bar.atop → /mnt/d/foo/bar.atop (用纯字符串避免 Path 的反斜杠)
        effective = str(atop_path)
        if self._use_wsl and len(effective) > 2 and effective[1] == ":":
            drive = effective[0].lower()
            rest = effective[2:].replace("\\", "/")
            effective = f"/mnt/{drive}{rest}"

        # 检查格式兼容性, 不兼容则自动转换
        actual_path = self._ensure_compatible_format(effective)

        # 用 -P 模式取 CPU + MEM
        cpu_data = self._parse_label(actual_path, "CPU")
        mem_data = self._parse_label(actual_path, "MEM")

        # 清理临时转换文件
        if actual_path != effective and "/tmp/" in actual_path:
            subprocess.run(
                ["bash", "-c", f'MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*" wsl -- /bin/rm -f "{actual_path}"'],
                capture_output=True, timeout=5
            )

        return {
            "file": str(atop_path),
            "frames_read": self.frames_read,
            "cpu": self._summarize_cpu(cpu_data),
            "mem": self._summarize_mem(mem_data),
            "errors": self.errors,
        }

    def _ensure_compatible_format(self, atop_path: str) -> str:
        """检测 atop 文件格式是否与当前 atop 版本兼容。
        不兼容时自动用 atopconvert 转换, 返回可读路径(str)。"""
        import tempfile

        # 先试直接读
        r = self._run_atop(["-r", atop_path, "-P", "CPU"], timeout=10)
        if r.returncode == 0:
            return atop_path

        # 检查是否格式不兼容
        stderr = r.stderr_str or ""
        if "incompatible format" in stderr or "atop-2." in stderr:
            try:
                # 复制到 WSL 内部 /tmp, 然后 atopconvert
                tmp_base = Path(tempfile.mktemp(suffix=".atop").replace("\\", "/"))
                # cp 文件到 WSL (/tmp)
                src = atop_path
                dst = f"/tmp/{tmp_base.name}"
                r_cp = subprocess.run(
                    ["bash", "-c", f'MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*" wsl -- /bin/cp "{src}" "{dst}"'],
                    capture_output=True, timeout=10
                )

                if r_cp.returncode != 0:
                    self.errors.append(f"cp to WSL failed: {r_cp.stderr.decode(errors='replace')[:200]}")
                    return atop_path

                # atopconvert inside WSL
                dst_new = f"/tmp/{tmp_base.name}.new"
                r2 = self._run_atop(["/usr/bin/atopconvert", dst, dst_new], timeout=30, binary="")
                if r2.returncode == 0:
                    # 清理源文件
                    subprocess.run(
                        ["bash", "-c", f'MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*" wsl -- /bin/rm -f "{dst}"'],
                        capture_output=True
                    )
                    return dst_new
            except Exception as e:
                self.errors.append(f"atopconvert failed: {str(e)[:200]}")

        return atop_path

    def _parse_label(self, atop_path: str, label: str) -> list[list[str]]:
        """跑 `atop -r <file> -P <LABEL>`,把每行 split 出来。"""
        try:
            r = self._run_atop(["-r", atop_path, "-P", label], timeout=30)
            if r.returncode != 0:
                self.errors.append(f"atop -P {label} failed: {r.stderr_str[:200]}")
                return []

            rows = []
            for line in r.stdout_str.splitlines():
                if line.startswith(label) or line.startswith("RESET"):
                    rows.append(line.split())
                    if line.startswith(label):
                        self.frames_read += 1
            return rows
        except subprocess.TimeoutExpired:
            self.errors.append(f"atop -P {label} timeout")
            return []

    @staticmethod
    def _summarize_cpu(rows: list[list[str]]) -> dict:
        """CPU label 字段含义见 atop man:
        CPU label format:
        CPU host epoch date time interval ticks_per_sec cpu_count
        sys user niced idle wait irq softirq steal guest freq freq_max

        注意:RESET 后第一帧 interval 字段是从 boot 起的累积,导致 sys+user 占 ticks 很高的比例
        但是 ticks 只是 1 秒的,所以 busy% 会爆炸。要丢弃 interval 异常的帧。
        """
        if not rows:
            return {}
        usage_pcts = []
        skipped_reset_frames = 0
        for r in rows:
            if r[0] != "CPU" or len(r) < 12:
                continue
            try:
                interval = int(r[5])  # 采样间隔(秒)
                ticks = int(r[6])
                cpu_count = int(r[7])
                sys_t = int(r[8])
                user_t = int(r[9])
                # interval 应该 == 1(atop 默认) 或对应配置值。如果显著不同则是 RESET 帧
                if interval <= 0 or interval > 120:
                    skipped_reset_frames += 1
                    continue
                # 总 ticks = ticks_per_sec * interval * cpu_count
                total = ticks * interval * cpu_count
                if total > 0:
                    busy_pct = 100 * (sys_t + user_t) / total
                    # busy_pct > 100 也是异常,丢
                    if 0 <= busy_pct <= 100:
                        usage_pcts.append(busy_pct)
                    else:
                        skipped_reset_frames += 1
            except (ValueError, IndexError):
                continue

        if not usage_pcts:
            return {"frames": 0, "skipped_reset_frames": skipped_reset_frames}
        return {
            "frames": len(usage_pcts),
            "skipped_reset_frames": skipped_reset_frames,
            "cpu_busy_pct_max": round(max(usage_pcts), 1),
            "cpu_busy_pct_avg": round(sum(usage_pcts) / len(usage_pcts), 1),
            "cpu_busy_pct_p95": round(sorted(usage_pcts)[int(len(usage_pcts) * 0.95)], 1),
            "high_cpu_frames": sum(1 for p in usage_pcts if p > 80),
        }

    @staticmethod
    def _summarize_mem(rows: list[list[str]]) -> dict:
        """MEM label format:
        MEM host epoch date time interval pagesize physmem freemem cachemem buffmem ...
        """
        if not rows:
            return {}
        used_pcts = []
        for r in rows:
            if r[0] != "MEM" or len(r) < 10:
                continue
            try:
                pagesize = int(r[6])
                physmem = int(r[7])
                freemem = int(r[8])
                if physmem > 0:
                    used_pct = 100 * (physmem - freemem) / physmem
                    used_pcts.append(used_pct)
            except (ValueError, IndexError):
                continue

        if not used_pcts:
            return {"frames": 0}
        return {
            "frames": len(used_pcts),
            "mem_used_pct_max": round(max(used_pcts), 1),
            "mem_used_pct_avg": round(sum(used_pcts) / len(used_pcts), 1),
        }
