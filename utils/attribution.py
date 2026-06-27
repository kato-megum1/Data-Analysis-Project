"""
归因引擎
- 加法型：直接增量占比法
- 乘法型：LMDI 对数分解法
"""

import numpy as np
import pandas as pd


class AttributionEngine:
    """异动归因分析引擎"""

    @staticmethod
    def additive_attribution(before: dict, after: dict) -> dict:
        """
        加法归因：直接增量占比
        输入: {"A": 100, "B": 200}, {"A": 80, "B": 250}
        输出: {"A": {"delta": -20, "contribution": -40%}, "B": {"delta": 50, "contribution": ...}}
        """
        total_before = sum(before.values())
        total_after = sum(after.values())
        total_delta = total_after - total_before

        if abs(total_delta) < 1e-10:
            return {k: {"delta": after.get(k, 0) - before.get(k, 0), "contribution_pct": 0,
                        "contribution_desc": "无变化"}
                    for k in set(before.keys()) | set(after.keys())}

        result = {}
        for key in set(before.keys()) | set(after.keys()):
            v_before = before.get(key, 0)
            v_after = after.get(key, 0)
            delta = v_after - v_before
            contrib = delta / total_delta * 100

            if abs(contrib) < 1:
                desc = "影响微小"
            elif contrib > 0:
                desc = f"正向贡献 {contrib:.1f}%，推动总量上升"
            else:
                desc = f"负向贡献 {abs(contrib):.1f}%，导致总量下降"

            result[key] = {
                "delta": delta,
                "contribution_pct": round(contrib, 1),
                "contribution_desc": desc
            }
        return result

    @staticmethod
    def multiplicative_attribution(before: dict, after: dict, total_key: str = None) -> dict:
        """
        乘法归因：LMDI 对数分解法
        用于 Y = X1 × X2 × ... × Xn 形式的归因
        通过取对数消除交叉项

        输入: {"DAU": 10000, "ARPU": 85}, {"DAU": 9000, "ARPU": 90}
        total_before = 10000 * 85 = 850000
        total_after = 9000 * 90 = 810000
        """
        # Calculate totals
        total_before = 1
        total_after = 1
        for key in before:
            total_before *= before[key]
        for key in after:
            total_after *= after[key]

        total_delta = total_after - total_before

        if abs(total_delta) < 1e-10:
            return {k: {"delta": 0, "contribution_pct": 0, "contribution_desc": "无变化"}
                    for k in before}

        # LMDI decomposition
        # For multiplication Y = ∏Xi
        # ln(Y1/Y0) contribution of Xi = ln(Xi1/Xi0) / ln(Y1/Y0) * ΔY
        ln_total_ratio = np.log(total_after / total_before)
        if abs(ln_total_ratio) < 1e-10:
            return {k: {"delta": 0, "contribution_pct": 0, "contribution_desc": "无变化"}
                    for k in before}

        result = {}
        for key in before:
            if key not in after:
                continue
            if before[key] == 0 or after[key] == 0:
                result[key] = {"delta": after[key] - before[key],
                                "contribution_pct": 0,
                                "contribution_desc": "无法计算对数（含零值）"}
                continue

            ln_factor_ratio = np.log(after[key] / before[key])
            contribution = (ln_factor_ratio / ln_total_ratio) * total_delta

            contrib_pct = contribution / total_delta * 100 if total_delta != 0 else 0

            if abs(contrib_pct) < 1:
                desc = "影响微小"
            elif contrib_pct > 0:
                desc = f"正向贡献 {contrib_pct:.1f}%（LMDI 分解），推动总量上升"
            else:
                desc = f"负向贡献 {abs(contrib_pct):.1f}%（LMDI 分解），导致总量下降"

            result[key] = {
                "delta": after[key] - before[key],
                "contribution_pct": round(contrib_pct, 1),
                "contribution_desc": desc
            }
        return result

    @staticmethod
    def drill_down(df: pd.DataFrame, metric_col: str, dimensions: list,
                   compare_col: str = None) -> list:
        """
        下钻分析：按维度优先级逐层拆解指标的变动

        参数:
            df: 数据框
            metric_col: 目标指标列名
            dimensions: 维度优先级列表 [("地区",), ("品类",)]
            compare_col: 用于对比的列（如时间周期标识）

        返回: 下钻树结构列表
        """
        drill_tree = []

        for level, dims in enumerate(dimensions):
            dim_list = dims if isinstance(dims, (list, tuple)) else [dims]
            group_cols = list(dim_list)

            if compare_col and compare_col in df.columns:
                grouped = df.groupby(group_cols + [compare_col])[metric_col].sum().unstack()
                if len(grouped.columns) >= 2:
                    grouped['delta'] = grouped.iloc[:, -1] - grouped.iloc[:, 0]
                    grouped['delta_pct'] = (grouped['delta'] / grouped.iloc[:, 0] * 100).round(1)
                    # Sort by absolute contribution
                    grouped = grouped.reindex(grouped['delta'].abs().sort_values(ascending=False).index)
                else:
                    grouped['avg'] = df.groupby(group_cols)[metric_col].mean()
            else:
                grouped = df.groupby(group_cols)[metric_col].agg(['sum', 'mean', 'count']).round(2)
                grouped = grouped.sort_values('sum', ascending=False)

            drill_tree.append({
                "level": level + 1,
                "dimensions": dim_list,
                "data": grouped.reset_index().to_dict('records'),
                "top_contributors": grouped.head(5).reset_index().to_dict('records') if isinstance(grouped, pd.DataFrame) else []
            })

        return drill_tree


def test_attribution():
    """测试归因算法"""
    engine = AttributionEngine()

    # Test additive
    add_result = engine.additive_attribution({"A": 100, "B": 200}, {"A": 80, "B": 250})
    assert add_result["A"]["delta"] == -20
    assert add_result["B"]["delta"] == 50
    print("✅ 加法归因测试通过:", add_result)

    # Test multiplicative
    mul_result = engine.multiplicative_attribution({"DAU": 10000, "ARPU": 85}, {"DAU": 9000, "ARPU": 90})
    assert "DAU" in mul_result
    print("✅ 乘法归因(LMDI)测试通过:", mul_result)

    print("✅ AttributionEngine 全部测试通过")


if __name__ == '__main__':
    test_attribution()
