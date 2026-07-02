"""
mcap_reader — MCAP 读取 (源自 roboonto 项目, 见 SOURCES.md)
====================================

读 MCAP 格式的 ROS2 bag,流式解析,把每条消息抽取成事件 / 标量时序。

依赖:
    pip install mcap mcap-ros2-support

设计原则:
- streaming(不一次性加载整个 bag)
- 按 topic 降采样(高频 topic 默认 1Hz 采样)
- 自动识别 ROS2 message 字段类型
- 隐私默认严格(剥离 image / pointcloud / audio)
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterator, Optional

try:
    from mcap.reader import make_reader
    from mcap_ros2.decoder import DecoderFactory
    HAS_MCAP = True
except ImportError:
    HAS_MCAP = False


# 默认每个 topic 最多保留 N 条消息(降采样)
MAX_MESSAGES_PER_TOPIC = 200

# 默认 drop 的 topic 模式(正则匹配)
PRIVACY_TOPIC_PATTERNS = [
    r"image", r"pointcloud", r"point_cloud", r"depth",
    r"audio", r"video", r"compressed", r"raw",
]


class McapReader:
    """流式读 MCAP bag,产出标准化事件。"""

    def __init__(self, max_per_topic: int = MAX_MESSAGES_PER_TOPIC):
        self.max_per_topic = max_per_topic
        self.topic_msg_count: Counter = Counter()
        self.topic_msg_type: dict[str, str] = {}
        self.topic_kept_count: Counter = Counter()
        self.privacy_skipped: Counter = Counter()

    def is_privacy_topic(self, topic: str) -> bool:
        import re
        for pat in PRIVACY_TOPIC_PATTERNS:
            if re.search(pat, topic, re.IGNORECASE):
                return True
        return False

    def read_messages(
        self,
        mcap_path: Path,
    ) -> Iterator[dict]:
        """
        流式产出消息字典,字段:
            topic: str
            msg_type: str
            log_time_ns: int
            publish_time_ns: int
            payload: dict (decoded message)
        """
        if not HAS_MCAP:
            raise RuntimeError(
                "mcap library not installed. Run: pip install mcap mcap-ros2-support"
            )

        with open(mcap_path, "rb") as f:
            reader = make_reader(f, decoder_factories=[DecoderFactory()])

            # 先扫一遍 channel 信息,知道有哪些 topic
            summary = reader.get_summary()
            if summary:
                for ch_id, channel in summary.channels.items():
                    schema = summary.schemas.get(channel.schema_id) if channel.schema_id else None
                    msg_type = schema.name if schema else "unknown"
                    self.topic_msg_type[channel.topic] = msg_type

            # 真实读取消息(streaming)
            for schema, channel, message, ros_msg in reader.iter_decoded_messages():
                topic = channel.topic
                self.topic_msg_count[topic] += 1

                # 隐私 drop:对所有匹配的 topic,直接跳过 payload
                if self.is_privacy_topic(topic):
                    self.privacy_skipped[topic] += 1
                    continue

                # 降采样:每个 topic 只保留前 N 条
                if self.topic_kept_count[topic] >= self.max_per_topic:
                    continue
                self.topic_kept_count[topic] += 1

                # 解码消息为 dict
                payload = self._ros_msg_to_dict(ros_msg)

                yield {
                    "topic": topic,
                    "msg_type": schema.name if schema else "unknown",
                    "log_time_ns": message.log_time,
                    "publish_time_ns": message.publish_time,
                    "payload": payload,
                }

    @staticmethod
    def _ros_msg_to_dict(msg, _depth: int = 0) -> dict:
        """把 mcap-ros2 解码出来的消息对象递归转成 dict。"""
        if _depth > 8:
            return {"__truncated__": True}

        if hasattr(msg, "__slots__"):
            result = {}
            for slot in msg.__slots__:
                val = getattr(msg, slot)
                result[slot] = McapReader._ros_msg_to_dict(val, _depth + 1)
            return result

        if isinstance(msg, (list, tuple)):
            # 数组类型,只保留前 32 项避免巨大 array
            return [McapReader._ros_msg_to_dict(x, _depth + 1) for x in msg[:32]]

        if isinstance(msg, (bytes, bytearray)):
            # 二进制数据(图像、点云等)直接 drop,只留长度
            return {"__binary__": True, "length": len(msg)}

        if isinstance(msg, dict):
            return {k: McapReader._ros_msg_to_dict(v, _depth + 1) for k, v in msg.items()}

        # 标量
        if isinstance(msg, (int, float, str, bool)) or msg is None:
            return msg

        # 其他类型 fallback
        try:
            return str(msg)[:200]
        except Exception:
            return "__unrenderable__"

    def get_stats(self) -> dict:
        return {
            "topics_total": len(self.topic_msg_count),
            "messages_total": sum(self.topic_msg_count.values()),
            "messages_kept": sum(self.topic_kept_count.values()),
            "privacy_skipped_topics": len(self.privacy_skipped),
            "privacy_skipped_messages": sum(self.privacy_skipped.values()),
            "topic_msg_count": dict(self.topic_msg_count),
            "topic_msg_type": dict(self.topic_msg_type),
        }
