"""
DeepSeek LLM 客户端 — LangChain 版本
封装 API 调用，提供数据分析场景的专用 prompt 模板

迁移说明：
- 底层从 urllib 手写调用改为 langchain-deepseek ChatDeepSeek
- 公共 API 完全保持不变（analyze_trends / analyze_anomaly / ... / chat）
- Prompt 仍使用 str.format() 模板替换（自定义覆盖机制不变）
- chat() 方法兼容旧的消息格式 [{"role": "...", "content": "..."}]
- 新增 _call_llm() 内部方法，统一处理 LangChain 调用 + 重试
"""

import json
import re
import time
from typing import Any, Optional, Union, List, Dict


def extract_json(text: str) -> dict:
    """
    从模型输出里稳健地抽取 JSON 对象。

    依次尝试：直接 json.loads → 去 ```json``` 围栏 → 抓第一个 {...} 子串。
    全部失败抛 ValueError。
    """
    if not isinstance(text, str):
        raise ValueError("LLM 输出非字符串")
    s = text.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # 去掉 markdown 代码围栏
    fenced = re.sub(r"^```(?:json)?|```$", "", s, flags=re.MULTILINE).strip()
    try:
        return json.loads(fenced)
    except json.JSONDecodeError:
        pass
    # 抓第一个花括号到最后一个花括号
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(s[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"无法解析为 JSON: {text[:200]}")


class LLMClient:
    """
    数据分析场景专用的 LLM 客户端

    内部使用 LangChain ChatDeepSeek，对外保持稳定的 API 接口。
    每个分析场景（趋势/异动/归因/评审/报告）封装为独立的调用方法。
    """

    MODEL = "deepseek-chat"
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds

    def __init__(self, api_key: str, prompts: dict = None):
        from langchain_deepseek import ChatDeepSeek
        from langchain_core.output_parsers import StrOutputParser

        self.custom_prompts = prompts or {}
        self.llm = ChatDeepSeek(
            model=self.MODEL,
            api_key=api_key,
        )
        self._str_parser = StrOutputParser()

    # ==================== Prompt 模板管理 ====================

    def _get_prompt(self, key: str, default_template: str, **kwargs) -> str:
        """使用自定义 prompt 模板（如果有）或默认模板，并填充变量"""
        template = self.custom_prompts.get(key, default_template)
        try:
            return template.format(**kwargs)
        except KeyError:
            # Fallback: if template references missing vars, use default
            return default_template.format(**kwargs)

    # ==================== 底层调用 ====================

    def _call_llm(self, messages: Union[List[Dict], List[Any]],
                  temperature: float = 0.3, max_tokens: int = 2048) -> str:
        """
        使用 LangChain ChatDeepSeek 调用 LLM，带重试机制

        messages 支持两种格式：
        1. 旧格式: [{"role": "system|user", "content": "..."}]
        2. LangChain Message 对象: [SystemMessage(...), HumanMessage(...)]
        """
        from langchain_core.messages import HumanMessage, SystemMessage, BaseMessage

        # 统一转换为 LangChain Message 对象
        lc_messages = []
        for m in messages:
            if isinstance(m, dict):
                role = m.get("role", "user")
                content = m.get("content", "")
                if role == "system":
                    lc_messages.append(SystemMessage(content=content))
                else:
                    lc_messages.append(HumanMessage(content=content))
            elif isinstance(m, BaseMessage):
                lc_messages.append(m)
            else:
                lc_messages.append(HumanMessage(content=str(m)))

        # 绑定参数并调用
        llm = self.llm.bind(temperature=temperature, max_tokens=max_tokens)

        for attempt in range(self.MAX_RETRIES):
            try:
                result = llm.invoke(lc_messages)
                return result.content
            except Exception as e:
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
                else:
                    raise RuntimeError(f"LLM API 调用失败: {e}")

    def chat(self, messages: Union[List[Dict], List[Any]],
             temperature: float = 0.3, max_tokens: int = 2048) -> str:
        """
        通用对话接口 — 兼容旧格式

        Args:
            messages: 消息列表，兼容旧 dict 格式或 LangChain Message 对象
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            LLM 返回的文本内容
        """
        return self._call_llm(messages, temperature=temperature, max_tokens=max_tokens)

    def structured_call(self, system: str, user: str,
                        temperature: float = 0.2, max_tokens: int = 2048) -> dict:
        """
        结构化输出接口：要求模型返回 JSON 对象，返回已解析的 dict。

        - 优先用 DeepSeek 的 JSON 模式（response_format）；不支持时自动降级。
        - 解析失败/调用失败带重试；全部失败抛 RuntimeError（调用方应自行兜底）。

        这是新架构里所有 LLM agent 的统一入口，取代各处手写的 ```json``` 抠取。
        """
        from langchain_core.messages import HumanMessage, SystemMessage

        msgs = [SystemMessage(content=system), HumanMessage(content=user)]
        json_mode = True
        last_err = None
        for attempt in range(self.MAX_RETRIES):
            try:
                kwargs = {"temperature": temperature, "max_tokens": max_tokens}
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                raw = self.llm.bind(**kwargs).invoke(msgs).content
                return extract_json(raw)
            except Exception as e:
                last_err = e
                json_mode = False  # 后续重试不再要求 JSON 模式，纯靠解析
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY * (attempt + 1))
        raise RuntimeError(f"structured_call 失败: {last_err}")

    # ==================== 专用 Prompt 模板 / Chain ====================

    def analyze_trends(self, metric_name: str, time_series: list,
                        change_data: dict) -> str:
        """趋势分析"""
        default = """你是资深数据分析师。请分析以下指标的趋势：

指标名称：{metric_name}
时间序列（最近几期）：{time_series}
环比变化：{change_data}

请用中文输出一段简洁的分析（150字以内），包含：
1. 整体趋势判断（上升/下降/平稳）
2. 最新一期变化的显著程度
3. 一句话建议"""
        prompt = self._get_prompt("analyze_trends", default,
            metric_name=metric_name,
            time_series=json.dumps(time_series, ensure_ascii=False),
            change_data=json.dumps(change_data, ensure_ascii=False))
        from langchain_core.messages import HumanMessage
        return self._call_llm(
            [HumanMessage(content=prompt)],
            temperature=0.3, max_tokens=512
        )

    def analyze_anomaly(self, metric_name: str, anomaly_result: dict,
                         context: str = "") -> str:
        """异动分析"""
        default = """你是资深数据分析师。检测到以下指标的异动：

指标名称：{metric_name}
异动详情：{anomaly_result}
数据上下文：{context}

请用中文分析（200字以内）：
1. 异动可能的业务原因（提出2-3个假设）
2. 建议的排查方向
3. 是否需要紧急关注"""
        prompt = self._get_prompt("analyze_anomaly", default,
            metric_name=metric_name,
            anomaly_result=json.dumps(anomaly_result, ensure_ascii=False),
            context=context)
        from langchain_core.messages import HumanMessage
        return self._call_llm(
            [HumanMessage(content=prompt)],
            temperature=0.5, max_tokens=512
        )

    def analyze_attribution(self, metric_name: str, attribution: dict,
                             drill_results: list) -> str:
        """归因分析"""
        default = """你是资深数据分析师。以下是异动归因分析结果：

指标：{metric_name}
归因分解：{attribution}
下钻结果：{drill_results}

请用中文输出（200字以内）：
1. 核心归因结论（谁是主要驱动因素）
2. 下钻发现的关键点
3. 业务建议"""
        prompt = self._get_prompt("analyze_attribution", default,
            metric_name=metric_name,
            attribution=json.dumps(attribution, ensure_ascii=False),
            drill_results=json.dumps(drill_results, ensure_ascii=False))
        from langchain_core.messages import HumanMessage
        return self._call_llm(
            [HumanMessage(content=prompt)],
            temperature=0.3, max_tokens=512
        )

    def data_review(self, findings: list, data_context: str) -> str:
        """数据视角评审"""
        default = """你是资深数据科学家。请从数据和方法论角度，挑战以下分析观点：

分析观点：
{findings}

数据背景：
{data_context}

请逐条审查，每一条用以下格式输出（不要编号，直接输出每个观点）：

【观点X的质疑】
- 统计层面：[你的质疑]
- 数据质量：[你的质疑]
- 方法选择：[是否建议更合适的统计方法]

只质疑真正有问题的地方，观点正确就说"通过"。总共不超过500字。"""
        prompt = self._get_prompt("data_review", default,
            findings=json.dumps(findings, ensure_ascii=False, indent=2),
            data_context=data_context)
        from langchain_core.messages import HumanMessage
        return self._call_llm(
            [HumanMessage(content=prompt)],
            temperature=0.4, max_tokens=1024
        )

    def biz_review(self, findings: list, business_context: str) -> str:
        """业务视角评审"""
        default = """你是资深业务分析师（零售/电商行业）。请从业务逻辑角度，挑战以下数据分析观点：

分析观点：
{findings}

业务场景：
{business_context}

请逐条审查，每一条用以下格式输出：

【观点X的业务质疑】
- 商业逻辑：[是否符合行业常识]
- 因果推断：[相关性是被误判为因果？]
- 外部因素：[是否忽略了可能的竞争/季节/政策干扰]
- 可操作性：[这个发现能否落地执行]

只质疑真正有问题的地方，观点正确就说"通过"。总共不超过500字。"""
        prompt = self._get_prompt("biz_review", default,
            findings=json.dumps(findings, ensure_ascii=False, indent=2),
            business_context=business_context)
        from langchain_core.messages import HumanMessage
        return self._call_llm(
            [HumanMessage(content=prompt)],
            temperature=0.5, max_tokens=1024
        )

    def rebuttal_response(self, original_findings: list,
                          data_review: str, biz_review: str) -> str:
        """回应评审意见"""
        default = """你是资深数据分析师。你的分析报告收到了数据和业务两方的评审意见。

你的原始观点：
{original_findings}

数据审阅意见：
{data_review}

业务审阅意见：
{biz_review}

请逐条回应，每条使用以下格式输出：

【对观点X的回应】
- 态度：[✅ 接受修正 / ❌ 维持原观点 / ⚠️ 标注不确定]
- 说明：[如果是接受修正，说明修正了什么；如果反驳，给出理由；如果标注不确定，说明局限]
- 最终置信度：[高 / 中高 / 中 / 中低 / 低]

总共不超过600字。"""
        prompt = self._get_prompt("rebuttal_response", default,
            original_findings=json.dumps(original_findings, ensure_ascii=False, indent=2),
            data_review=data_review,
            biz_review=biz_review)
        from langchain_core.messages import HumanMessage
        return self._call_llm(
            [HumanMessage(content=prompt)],
            temperature=0.3, max_tokens=1536
        )

    def generate_report(self, analysis_data: dict) -> str:
        """生成周报风格的报告摘要"""
        default = """你是资深数据分析师，需要撰写一份专业的数据分析周报。

分析数据：
{analysis_data}

请撰写完整的报告正文（Markdown 格式），要求：

## 一、核心摘要
用一段话概括本期数据表现（100字左右）

## 二、各指标详析
每个分析指标一段，包括趋势、变化幅度、关键发现

## 三、异动专项
如有异常指标，详细说明发现原因和归因结果（如无异常则说明"本期各项指标运行平稳"）

## 四、围栏指标
如有围栏指标，汇报状态（正常/越界），如越界则说明原因

## 五、风险提示与建议
基于数据发现的行动建议

风格要求：
- 专业但不晦涩，面向业务负责人
- 用数据说话，避免主观臆断
- 关键数字用 **加粗** 突出
- 有结论有建议，不是流水账
- 总字数 600-1000 字"""
        prompt = self._get_prompt("generate_report", default,
            analysis_data=json.dumps(analysis_data, ensure_ascii=False, indent=2))
        from langchain_core.messages import HumanMessage
        return self._call_llm(
            [HumanMessage(content=prompt)],
            temperature=0.4, max_tokens=2048
        )

    # ==================== 高级功能：Chain / Runnable ====================

    def get_chain(self, prompt_template: str, temperature: float = 0.3,
                  max_tokens: int = 2048):
        """
        获取一个 LangChain RunnableSequence（PromptTemplate | LLM | Parser）

        用于需要灵活组合的场景。示例：
            chain = llm_client.get_chain("分析{topic}的趋势", temperature=0.5)
            result = chain.invoke({"topic": "销售额"})

        Args:
            prompt_template: prompt 模板字符串，支持 {var} 占位符
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            RunnableSequence 对象，可直接 .invoke() / .batch() / .stream()
        """
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_messages([
            ("human", prompt_template)
        ])
        llm = self.llm.bind(temperature=temperature, max_tokens=max_tokens)
        return prompt | llm | self._str_parser

    def get_chat_chain(self, system_prompt: str = "", temperature: float = 0.3,
                       max_tokens: int = 2048):
        """
        获取一个带 system prompt 的 Chat Chain

        示例：
            chain = llm_client.get_chat_chain("你是数据分析专家", temperature=0.5)
            result = chain.invoke({"input": "分析下销售额为什么下降"})
        """
        from langchain_core.prompts import ChatPromptTemplate

        messages = [("human", "{input}")]
        if system_prompt:
            messages.insert(0, ("system", system_prompt))
        prompt = ChatPromptTemplate.from_messages(messages)
        llm = self.llm.bind(temperature=temperature, max_tokens=max_tokens)
        return prompt | llm | self._str_parser

    def stream_chat(self, messages: Union[List[Dict], List[Any]],
                    temperature: float = 0.3, max_tokens: int = 2048):
        """
        流式输出接口（LangChain 原生支持）

        示例：
            for chunk in llm_client.stream_chat([{"role": "user", "content": "你好"}]):
                print(chunk, end="")
        """
        from langchain_core.messages import HumanMessage, SystemMessage, BaseMessage

        # 统一转换为 LangChain Message 对象
        lc_messages = []
        for m in messages:
            if isinstance(m, dict):
                role = m.get("role", "user")
                content = m.get("content", "")
                if role == "system":
                    lc_messages.append(SystemMessage(content=content))
                else:
                    lc_messages.append(HumanMessage(content=content))
            elif isinstance(m, BaseMessage):
                lc_messages.append(m)
            else:
                lc_messages.append(HumanMessage(content=str(m)))

        llm = self.llm.bind(temperature=temperature, max_tokens=max_tokens)
        return llm.stream(lc_messages)


# ==================== 测试 ====================

def test_llm_client():
    """简单连通性测试（需要 API Key）"""
    import os
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("⚠️ 跳过 LLM 测试（未设置 DEEPSEEK_API_KEY）")
        return

    client = LLMClient(api_key)
    try:
        result = client.chat([{"role": "user", "content": "回复'pong'即可"}],
                             temperature=0, max_tokens=10)
        print(f"✅ LLM 连通性测试通过: {result}")
    except Exception as e:
        print(f"❌ LLM 测试失败: {e}")


if __name__ == '__main__':
    test_llm_client()
