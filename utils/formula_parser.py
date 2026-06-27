"""
四则运算公式解析器
支持 + - * / ( ) 和列名引用
用法: parser = FormulaParser(df); result = parser.eval("GMV = DAU * ARPU")
"""

import re
import operator
import pandas as pd
import numpy as np

class FormulaParser:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.column_names = list(df.columns)

    def eval_formula(self, formula_str: str) -> pd.Series:
        """
        解析公式字符串，返回计算结果
        例: "DAU * ARPU" → df['DAU'] * df['ARPU']
            "A + B - C" → df['A'] + df['B'] - df['C']
        """
        expr = formula_str.strip()
        # Replace column names with df references
        # Sort by length descending to match longer names first
        sorted_cols = sorted(self.column_names, key=len, reverse=True)
        col_map = {}
        for col in sorted_cols:
            # Escape special regex chars, use word boundary to avoid partial matches
            escaped_col = re.escape(col)
            placeholder = f"__COL_{len(col_map)}__"
            pattern = r'\b' + escaped_col + r'\b'
            if re.search(pattern, expr):
                col_map[placeholder] = col
                expr = re.sub(pattern, placeholder, expr)

        if not col_map:
            raise ValueError(f"未找到匹配的列名: {formula_str}")

        # Build safe eval context
        context = {}
        for placeholder, col in col_map.items():
            context[placeholder] = self.df[col].astype(float)

        # Parse and evaluate expression tree
        result = self._eval_expression(expr, context)
        return pd.Series(result, index=self.df.index)

    def _eval_expression(self, expr: str, context: dict) -> np.ndarray:
        """安全地求值四则运算表达式"""
        # Tokenize
        tokens = self._tokenize(expr)
        # Parse to AST
        ast = self._parse(tokens)
        # Evaluate AST
        return self._eval_node(ast, context)

    def _tokenize(self, expr: str):
        """词法分析：将表达式拆分为 token 列表"""
        tokens = []
        i = 0
        while i < len(expr):
            c = expr[i]
            if c.isspace():
                i += 1
                continue
            if c in '+-*/()':
                tokens.append(('OP', c))
                i += 1
            elif c.isdigit() or c == '.':
                j = i
                while j < len(expr) and (expr[j].isdigit() or expr[j] == '.'):
                    j += 1
                tokens.append(('NUM', float(expr[i:j])))
                i = j
            elif c.isalpha() or c == '_':
                # Match column placeholders like __COL_0__
                j = i
                while j < len(expr) and (expr[j].isalnum() or expr[j] == '_'):
                    j += 1
                name = expr[i:j]
                tokens.append(('NAME', name))
                i = j
            else:
                raise ValueError(f"非法字符: {c} (位置 {i})")
        return tokens

    def _parse(self, tokens):
        """语法分析：递归下降解析，生成 AST"""
        self._pos = 0
        self._tokens = tokens
        result = self._parse_add_sub()
        if self._pos < len(self._tokens):
            raise ValueError(f"意外的 token: {self._tokens[self._pos]}")
        return result

    def _parse_add_sub(self):
        """处理加减法（最低优先级）"""
        left = self._parse_mul_div()
        while self._pos < len(self._tokens):
            t_type, t_val = self._tokens[self._pos]
            if t_type == 'OP' and t_val in '+-':
                self._pos += 1
                right = self._parse_mul_div()
                left = ('binop', t_val, left, right)
            else:
                break
        return left

    def _parse_mul_div(self):
        """处理乘除法"""
        left = self._parse_unary()
        while self._pos < len(self._tokens):
            t_type, t_val = self._tokens[self._pos]
            if t_type == 'OP' and t_val in '*/':
                self._pos += 1
                right = self._parse_unary()
                left = ('binop', t_val, left, right)
            else:
                break
        return left

    def _parse_unary(self):
        """处理一元运算符和括号"""
        if self._pos >= len(self._tokens):
            raise ValueError("表达式不完整")
        t_type, t_val = self._tokens[self._pos]
        if t_type == 'OP' and t_val == '-':
            self._pos += 1
            return ('unary', '-', self._parse_unary())
        elif t_type == 'OP' and t_val == '(':
            self._pos += 1
            result = self._parse_add_sub()
            if self._pos >= len(self._tokens) or self._tokens[self._pos] != ('OP', ')'):
                raise ValueError("缺少右括号")
            self._pos += 1
            return result
        elif t_type in ('NUM', 'NAME'):
            self._pos += 1
            return ('leaf', t_type, t_val)
        else:
            raise ValueError(f"意外的 token: {(t_type, t_val)}")

    def _eval_node(self, node, context):
        """递归求值 AST 节点"""
        if node[0] == 'leaf':
            _, t_type, t_val = node
            if t_type == 'NUM':
                return np.full(len(next(iter(context.values()))), t_val)
            else:  # NAME
                if t_val not in context:
                    raise ValueError(f"未定义的列: {t_val}")
                return context[t_val]
        elif node[0] == 'unary':
            _, op, child = node
            val = self._eval_node(child, context)
            return -val
        elif node[0] == 'binop':
            _, op, left, right = node
            l_val = self._eval_node(left, context)
            r_val = self._eval_node(right, context)
            ops = {'+': operator.add, '-': operator.sub, '*': operator.mul, '/': operator.truediv}
            if op not in ops:
                raise ValueError(f"不支持的运算符: {op}")
            return ops[op](l_val, r_val)
        else:
            raise ValueError(f"未知 AST 节点: {node[0]}")

    def parse_formula_assignment(self, formula_str: str):
        """解析赋值形式的公式，如 "GMV = DAU * ARPU"，返回 (name, expr)"""
        if '=' in formula_str:
            parts = formula_str.split('=', 1)
            name = parts[0].strip()
            expr = parts[1].strip()
            return name, expr
        return None, formula_str.strip()

    def get_formula_type(self, expr: str) -> str:
        """
        判断公式类型
        'additive': 纯加法/减法
        'multiplicative': 纯乘法
        'mixed': 混合
        """
        tokens = self._tokenize(expr)
        ops = [t[1] for t in tokens if t[0] == 'OP' and t[1] in '+-*/']

        has_add_sub = any(op in '+-' for op in ops)
        has_mul_div = any(op in '*/' for op in ops)

        if has_add_sub and not has_mul_div:
            return 'additive'
        elif has_mul_div and not has_add_sub:
            return 'multiplicative'
        else:
            return 'mixed'


def test_formula_parser():
    """简单测试"""
    df = pd.DataFrame({'A': [10, 20, 30], 'B': [1, 2, 3], 'C': [5, 5, 5]})
    parser = FormulaParser(df)

    assert list(parser.eval_formula('A + B')) == [11, 22, 33]
    assert list(parser.eval_formula('A * B')) == [10, 40, 90]
    assert list(parser.eval_formula('(A + B) * C')) == [55, 110, 165]

    name, expr = parser.parse_formula_assignment('GMV = A * B')
    assert name == 'GMV'
    assert expr == 'A * B'

    assert parser.get_formula_type('A + B') == 'additive'
    assert parser.get_formula_type('A * B') == 'multiplicative'
    assert parser.get_formula_type('A * B + C') == 'mixed'

    print("✅ FormulaParser 测试通过")


if __name__ == '__main__':
    test_formula_parser()
