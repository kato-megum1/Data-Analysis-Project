"""
异动检测器
- 阈值法：环比/同比变化超过设定百分比
- 统计法：Z-score 基于历史窗口
- 双重验证：两者交叉确认
"""

import numpy as np
from scipy import stats as scipy_stats
from typing import Optional


class AnomalyDetector:
    def __init__(self, window: int = 4, z_threshold: float = 2.0):
        """
        window: Z-score 计算的历史窗口期数
        z_threshold: Z-score 阈值（默认 ±2 标准差）
        """
        self.window = window
        self.z_threshold = z_threshold

    def detect(self, series: np.ndarray,
               down_threshold: Optional[float] = None,
               up_threshold: Optional[float] = None) -> dict:
        """
        综合异动检测

        参数:
            series: 时间序列数据（至少需要 window+1 个数据点）
            down_threshold: 环比下降告警阈值（百分比，如 15 表示 15%）
            up_threshold: 环比上升告警阈值（百分比）

        返回:
            {
                "is_anomaly": bool,
                "confidence": "high" | "low" | "none",
                "change_pct": float,        # 最新一期环比变化%
                "z_score": float,            # Z-score
                "threshold_triggered": bool, # 阈值是否触发
                "statistical_triggered": bool, # 统计方法是否触发
                "detail": str
            }
        """
        if len(series) < 2:
            return self._no_anomaly("数据点不足，无法检测")

        current = series[-1]
        previous = series[-2]
        change_pct = ((current - previous) / previous * 100) if previous != 0 else 0

        threshold_triggered = False
        has_threshold = down_threshold is not None or up_threshold is not None

        # 1. Check thresholds
        if down_threshold is not None and change_pct <= -abs(down_threshold):
            threshold_triggered = True
        if up_threshold is not None and change_pct >= abs(up_threshold):
            threshold_triggered = True

        # 2. Statistical check (Z-score)
        statistical_triggered = False
        z_score = 0.0
        if len(series) >= self.window:
            history = series[-(self.window + 1):-1]
            mean = np.mean(history)
            std = np.std(history)
            if std > 1e-10:
                z_score = (current - mean) / std
                if abs(z_score) > self.z_threshold:
                    statistical_triggered = True

        # 3. Combined judgment
        if has_threshold:
            if threshold_triggered and statistical_triggered:
                confidence = "high"
                detail = f"高置信度异常：环比变化 {change_pct:+.1f}%，超过阈值，且 Z-score={z_score:.1f} 超出 ±{self.z_threshold} 范围"
            elif threshold_triggered:
                confidence = "low"
                detail = f"低置信度异常：环比变化 {change_pct:+.1f}%，超过阈值，但 Z-score={z_score:.1f} 未触发统计告警"
            elif statistical_triggered:
                confidence = "low"
                detail = f"低置信度异常：Z-score={z_score:.1f} 触发统计告警，但环比变化 {change_pct:+.1f}% 未超过设定阈值"
            else:
                confidence = "none"
                detail = f"未检测到异常：环比变化 {change_pct:+.1f}%，Z-score={z_score:.1f}"
        else:
            if statistical_triggered:
                confidence = "high" if abs(z_score) > 3 else "low"
                detail = f"统计异动：Z-score={z_score:.1f}，环比变化 {change_pct:+.1f}%"
            else:
                confidence = "none"
                detail = f"未检测到异常：Z-score={z_score:.1f}，环比变化 {change_pct:+.1f}%"

        return {
            "is_anomaly": confidence in ("high", "low"),
            "confidence": confidence,
            "change_pct": round(change_pct, 1),
            "z_score": round(z_score, 2),
            "threshold_triggered": threshold_triggered,
            "statistical_triggered": statistical_triggered,
            "detail": detail
        }

    def detect_all_periods(self, series: np.ndarray,
                           down_threshold: Optional[float] = None,
                           up_threshold: Optional[float] = None) -> list:
        """返回每个时间点的异动检测结果"""
        results = []
        for i in range(1, len(series)):
            sub_series = series[:i + 1]
            result = self.detect(sub_series, down_threshold, up_threshold)
            result["period_index"] = i
            results.append(result)
        return results

    def _no_anomaly(self, reason: str) -> dict:
        return {
            "is_anomaly": False,
            "confidence": "none",
            "change_pct": 0,
            "z_score": 0,
            "threshold_triggered": False,
            "statistical_triggered": False,
            "detail": reason
        }


def test_anomaly_detector():
    detector = AnomalyDetector(window=4, z_threshold=2.0)

    # Normal data
    normal = np.array([100, 102, 98, 101, 99, 103])
    r = detector.detect(normal, down_threshold=15, up_threshold=20)
    assert not r["is_anomaly"]
    print("✅ 正常数据检测:", r["detail"])

    # Anomalous drop
    drop = np.array([100, 102, 98, 101, 99, 50])
    r = detector.detect(drop, down_threshold=15, up_threshold=20)
    assert r["is_anomaly"]
    print("✅ 异常下降检测:", r["detail"])

    # Without threshold
    r2 = detector.detect(drop)
    assert r2["statistical_triggered"]
    print("✅ 纯统计检测:", r2["detail"])

    print("✅ AnomalyDetector 全部测试通过")


if __name__ == '__main__':
    test_anomaly_detector()
