"""
MCAP Joint State Parser — 从 rt_control_link mcap 提取左右腿关节角度/力矩
使用二进制扫描法绕过 ROS2 CDR 序列化格式复杂性
"""
from mcap.reader import make_reader
from pathlib import Path
import struct
import json
import math
from typing import Optional

# 灵犀X2 所有腿部关节名 (URDF 定义)
LEG_JOINTS = [
    "left_hip_pitch_joint", "left_hip_roll_joint", "left_hip_yaw_joint",
    "left_knee_joint", "left_ankle_pitch_joint", "left_ankle_roll_joint",
    "right_hip_pitch_joint", "right_hip_roll_joint", "right_hip_yaw_joint",
    "right_knee_joint", "right_ankle_pitch_joint", "right_ankle_roll_joint",
]

LEFT_JOINTS = [j for j in LEG_JOINTS if j.startswith("left_")]
RIGHT_JOINTS = [j for j in LEG_JOINTS if j.startswith("right_")]

PAIR_MAP = {
    "left_hip_pitch_joint": "right_hip_pitch_joint",
    "left_hip_roll_joint": "right_hip_roll_joint",
    "left_hip_yaw_joint": "right_hip_yaw_joint",
    "left_knee_joint": "right_knee_joint",
    "left_ankle_pitch_joint": "right_ankle_pitch_joint",
    "left_ankle_roll_joint": "right_ankle_roll_joint",
}


def scan_joints_in_message(data: bytes) -> dict:
    """在单条 CDR 消息的二进制数据中扫描关节名字符串，提取后跟的 3 个 float64"""
    result = {}
    for name in LEG_JOINTS:
        name_bytes = name.encode()
        idx = data.find(name_bytes)
        if idx < 0:
            continue
        # 关节名字符串后紧跟 24 字节: position(8) + velocity(8) + effort(8)
        val_start = idx + len(name_bytes)
        # CDR 对齐到 4 字节边界
        val_start = (val_start + 3) & ~3
        if val_start + 24 > len(data):
            continue
        try:
            pos = struct.unpack_from("<d", data, val_start)[0]
            vel = struct.unpack_from("<d", data, val_start + 8)[0]
            eff = struct.unpack_from("<d", data, val_start + 16)[0]
            # 过滤掉明显的垃圾值 (CDR 解析错位)
            if math.isfinite(pos) and math.isfinite(eff) and abs(pos) < 100 and abs(eff) < 10000:
                result[name] = {"position": pos, "velocity": vel, "effort": eff}
        except struct.error:
            continue
    return result


def parse_leg_states(mcap_path: str, max_samples: int = 500000) -> list:
    """从 mcap 文件提取所有腿部关节状态"""
    path = Path(mcap_path)
    if not path.exists():
        raise FileNotFoundError(f"MCAP not found: {mcap_path}")

    file_size_mb = path.stat().st_size / (1024 * 1024)
    print(f"[mcap] Reading: {path.name} ({file_size_mb:.1f} MB)")

    samples = []
    with open(path, "rb") as f:
        reader = make_reader(f)
        for schema, channel, msg in reader.iter_messages():
            if channel.topic == "/aima/hal/joint/leg/state":
                joints = scan_joints_in_message(msg.data)
                if len(joints) >= 8:  # 至少 8 个关节才认为解析有效
                    samples.append({
                        "ts_ns": msg.log_time,
                        "joints": joints,
                    })
                if len(samples) >= max_samples:
                    break

    if not samples:
        raise RuntimeError("No leg state messages found in MCAP")

    t0 = samples[0]["ts_ns"]
    t1 = samples[-1]["ts_ns"]
    duration_s = (t1 - t0) / 1e9
    rate = len(samples) / duration_s if duration_s > 0 else 0
    print(f"[mcap] Extracted {len(samples)} samples over {duration_s:.1f}s ({rate:.0f} Hz)")
    return samples


def compute_asymmetry(samples: list) -> dict:
    """计算左右腿关节的不对称指标"""
    n = len(samples)
    if n == 0:
        return {}

    # 累加
    l_eff = {j: 0.0 for j in LEFT_JOINTS}
    r_eff = {j: 0.0 for j in RIGHT_JOINTS}
    l_pos = {j: 0.0 for j in LEFT_JOINTS}
    r_pos = {j: 0.0 for j in RIGHT_JOINTS}
    l_vel = {j: 0.0 for j in LEFT_JOINTS}
    r_vel = {j: 0.0 for j in RIGHT_JOINTS}

    for s in samples:
        jd = s["joints"]
        for jn in LEFT_JOINTS:
            if jn in jd:
                l_eff[jn] += abs(jd[jn]["effort"])
                l_pos[jn] += jd[jn]["position"]
                l_vel[jn] += abs(jd[jn]["velocity"])
        for jn in RIGHT_JOINTS:
            if jn in jd:
                r_eff[jn] += abs(jd[jn]["effort"])
                r_pos[jn] += jd[jn]["position"]
                r_vel[jn] += abs(jd[jn]["velocity"])

    # 均值
    result = {
        "sample_count": n,
        "pairs": [],
    }

    total_asymmetry_score = 0.0
    for ln in LEFT_JOINTS:
        rn = PAIR_MAP[ln]
        le = l_eff[ln] / n
        re = r_eff[rn] / n
        lp = l_pos[ln] / n
        rp = r_pos[rn] / n
        lv = l_vel[ln] / n
        rv = r_vel[rn] / n

        eff_ratio = re / le if le > 0.01 else (999 if re > 0.01 else 1.0)
        pos_diff_deg = (rp - lp) * 180 / math.pi

        # 不对称分数: 位置差(度) + 力矩比偏离1的程度
        asymmetry_score = abs(pos_diff_deg) + abs(math.log2(max(eff_ratio, 1 / eff_ratio)))
        total_asymmetry_score += asymmetry_score

        pair = {
            "left_joint": ln,
            "right_joint": rn,
            "left_effort_mean": round(le, 4),
            "right_effort_mean": round(re, 4),
            "effort_ratio_r_over_l": round(eff_ratio, 2),
            "left_position_mean_deg": round(lp * 180 / math.pi, 2),
            "right_position_mean_deg": round(rp * 180 / math.pi, 2),
            "position_diff_deg": round(pos_diff_deg, 2),
            "left_velocity_mean": round(lv, 4),
            "right_velocity_mean": round(rv, 4),
            "asymmetry_score": round(asymmetry_score, 2),
        }
        result["pairs"].append(pair)

    result["total_asymmetry_score"] = round(total_asymmetry_score, 2)
    result["severity"] = (
        "CRITICAL" if total_asymmetry_score > 30 else
        "WARNING" if total_asymmetry_score > 10 else
        "NORMAL"
    )

    return result


def print_asymmetry_report(result: dict) -> None:
    """打印人类可读的不对称报告"""
    print(f"\n{'='*90}")
    print(f"  关节对称性分析 (n={result['sample_count']} samples)")
    print(f"  总体不对称分数: {result['total_asymmetry_score']} → {result['severity']}")
    print(f"{'='*90}")
    print(f"{'关节对':<30} {'L_力矩':>8} {'R_力矩':>8} {'R/L':>8} || {'L_角度':>8} {'R_角度':>8} {'差值°':>8} || {'评分':>6}")
    print("-" * 90)
    for p in result["pairs"]:
        flag = " ⚠️" if abs(p["position_diff_deg"]) > 5 or p["effort_ratio_r_over_l"] > 3 or p["effort_ratio_r_over_l"] < 0.3 else ""
        print(
            f"{p['left_joint']:<30} {p['left_effort_mean']:>8.2f} {p['right_effort_mean']:>8.2f} "
            f"{p['effort_ratio_r_over_l']:>8.2f} || {p['left_position_mean_deg']:>8.1f}° "
            f"{p['right_position_mean_deg']:>8.1f}° {p['position_diff_deg']:>+8.1f}° || {p['asymmetry_score']:>5.1f}{flag}"
        )
    print()


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python mcap_joint_parser.py <mcap_file> [--json]")
        sys.exit(1)

    mcap_path = sys.argv[1]
    samples = parse_leg_states(mcap_path)
    result = compute_asymmetry(samples)

    if "--json" in sys.argv:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_asymmetry_report(result)
