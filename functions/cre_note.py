"""
note_generator.py
智能笔记生成模块 - 完整版（单独处理音频特有内容）
"""

import os
import json
import time
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import re
import random

from config import Config


class NoteGenerator:
    """
    智能笔记生成器 - 针对 GLM-4-Flash-250414 优化的分块处理版本
    """

    def __init__(self, api_key: str = None, base_url: str = None, debug_mode: bool = True):
        self.api_key = api_key or Config.GLM_API_KEY
        self.base_url = base_url or Config.GLM_BASE_URL
        self.debug_mode = debug_mode
        self.timeout_seconds = 90

        self.temperature = 0.6
        self.max_tokens = 3000
        self.top_p = 0.95

        if not self.api_key:
            raise ValueError("GLM API 密钥未设置")

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        if self.debug_mode:
            print(f"🔧 NoteGenerator 初始化完成")
            print(f"  - API 端点: {self.base_url}")
            print(f"  - 参数: temperature={self.temperature}, max_tokens={self.max_tokens}, top_p={self.top_p}")

    def _call_glm_api(self, prompt: str, system_prompt: str = None,
                      max_retries: int = 3) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": "glm-4-flash-250414",
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens
        }

        consecutive_429_count = 0

        for attempt in range(max_retries):
            try:
                if self.debug_mode and attempt > 0:
                    print(f"  🔄 第 {attempt + 1}/{max_retries} 次尝试...")

                response = requests.post(
                    self.base_url,
                    headers=self.headers,
                    json=payload,
                    timeout=self.timeout_seconds
                )

                if response.status_code != 200:
                    error_data = response.json() if response.text else {}
                    error_code = error_data.get("error", {}).get("code", "unknown")
                    error_msg = error_data.get("error", {}).get("message", response.text[:300])

                    if self.debug_mode:
                        print(f"❌ API 调用失败: {response.status_code} (错误码: {error_code})")
                        print(f"错误详情: {error_msg}")

                    if response.status_code == 429 or error_code == "1302":
                        consecutive_429_count += 1
                        wait_time = min(15 * (2 ** (consecutive_429_count - 1)), 60)

                        if attempt < max_retries - 1:
                            print(f"🚦 触发速率限制(1302)，等待 {wait_time} 秒后重试... ({consecutive_429_count}次)")
                            time.sleep(wait_time)
                            continue
                        else:
                            raise Exception(f"API 速率限制(1302)，已重试{max_retries}次仍失败，请稍后重试")

                    raise Exception(f"API 调用失败: {response.status_code} - {error_msg}")

                result = response.json()
                if not result.get("choices"):
                    raise Exception("API 返回空 choices")

                content = result["choices"][0].get("message", {}).get("content", "")
                if not content:
                    reasoning = result["choices"][0].get("message", {}).get("reasoning_content", "")
                    if reasoning:
                        content = reasoning
                    else:
                        raise Exception("API 返回空内容")

                if self.debug_mode:
                    print(f"  ✅ API 调用成功，返回长度: {len(content)} 字符")

                consecutive_429_count = 0
                return content.strip()

            except requests.exceptions.ReadTimeout:
                if attempt < max_retries - 1:
                    if self.debug_mode:
                        print(f"  ⏱️ 请求超时，等待5秒后重试...")
                    time.sleep(5)
                else:
                    raise Exception(f"API 请求超时，已重试 {max_retries} 次")

            except Exception as e:
                error_str = str(e)
                if "1302" in error_str or "429" in error_str or "速率限制" in error_str:
                    consecutive_429_count += 1
                    if attempt < max_retries - 1:
                        wait_time = min(15 * (2 ** (consecutive_429_count - 1)), 60)
                        print(f"🚦 检测到速率限制，等待 {wait_time} 秒后重试...")
                        time.sleep(wait_time)
                        continue

                if attempt < max_retries - 1:
                    time.sleep(2)
                else:
                    raise

    def _chunk_pages(self, pages: List[Dict], chunk_size: int = 3) -> List[List[Dict]]:
        return [pages[i:i + chunk_size] for i in range(0, len(pages), chunk_size)]

    def _extract_page_context(self, pages: List[Dict], include_audio_only: bool = False,
                             audio_only_content: List = None) -> Tuple[str, Dict]:
        context_parts = []
        metadata = {
            "pages_included": len(pages),
            "total_main_points": 0,
            "total_formulas": 0
        }

        for i, page in enumerate(pages, 1):
            slide_title = page.get("slide_title", f"第{i}页")
            knowledge_category = page.get("knowledge_category", "未分类")
            main_points = page.get("main_points", [])
            formulas = page.get("formulas", [])
            slide_summary = page.get("slide_summary", "")
            audio_segments = page.get("audio_segments", [])
            ocr_text = page.get("ocr_text", "")[:300]

            context_parts.append(f"=== {slide_title} ===")
            if knowledge_category != "未分类":
                context_parts.append(f"分类: {knowledge_category}")

            if main_points:
                context_parts.append("要点:")
                for point in main_points:
                    context_parts.append(f"- {point}")
                metadata["total_main_points"] += len(main_points)

            if formulas:
                context_parts.append("公式:")
                for formula in formulas:
                    clean_formula = formula.replace('\\\\', '\\')
                    context_parts.append(f"${clean_formula}$")
                metadata["total_formulas"] += len(formulas)

            if ocr_text and len(ocr_text) > 20:
                context_parts.append(f"原文: {ocr_text}")

            if audio_segments:
                key_audio = self._filter_teacher_chatter(audio_segments)
                if key_audio:
                    context_parts.append("讲解:")
                    for text in key_audio[:2]:
                        context_parts.append(f"> {text[:200]}")

            if slide_summary and len(slide_summary) < 150:
                context_parts.append(f"摘要: {slide_summary}")

            context_parts.append("")

        # 注意：不再在这里处理音频特有内容，改为单独处理
        return "\n".join(context_parts), metadata

    def _extract_audio_context(self, audio_segments: List[Dict]) -> str:
        """
        提取音频特有内容的上下文
        """
        context_parts = []

        for i, seg in enumerate(audio_segments, 1):
            if isinstance(seg, dict):
                start = seg.get("start", "")
                end = seg.get("end", "")
                text = seg.get("text", "")

                if text and len(text.strip()) >= 15:  # 保留有意义的内容
                    # 添加序号、时间戳和文本
                    context_parts.append(f"{i}. [{start}-{end}] {text}")

        return "\n".join(context_parts)

    def _filter_teacher_chatter(self, audio_segments, is_list: bool = False) -> List[str]:
        chatter_patterns = [
            r'这个.*啊', r'那个.*啊', r'就是说', r'那么',
            r'大家', r'我们.*看', r'注意.*啊', r'好.*现在',
            r'接下来', r'上一.*讲', r'回忆.*', r'有没有问题',
            r'听懂.*', r'明白.*', r'对吧', r'是吧'
        ]

        knowledge_keywords = ['定义', '公式', '定理', '推导', '因为', '所以',
                              '等于', '大于', '小于', '函数', '变量', '结论',
                              '本质', '原理', '关键', '核心', '概念', '性质',
                              '证明', '计算', '结果', '方法', '步骤', '例子']

        filtered = []

        items = []
        for seg in audio_segments:
            if isinstance(seg, dict):
                text = seg.get("text", "")
                if not text:
                    text = seg.get("content", "") or seg.get("transcript", "")
            else:
                text = str(seg)

            if text and len(text.strip()) > 0:
                items.append(text)

        for text in items:
            if len(text.strip()) < 15:
                continue

            chatter_score = sum(1 for p in chatter_patterns if re.search(p, text))
            knowledge_score = sum(1 for kw in knowledge_keywords if kw in text)

            if knowledge_score >= 1 or (len(text) > 80 and chatter_score < 2):
                cleaned = re.sub(r'^(那么|这个|那个|好|我们|大家|请|啊)+[，,.\s]*', '', text)
                filtered.append(cleaned)

        return filtered

    def _generate_chunk_notes(self, chunk_context: str, chunk_index: int,
                             total_chunks: int, previous_summary: str = "") -> str:
        continuity_prompt = f"\n前文摘要: {previous_summary}\n请保持内容连贯。" if previous_summary else ""

        prompt = f"""你是学术笔记整理专家。请根据以下提供的**课件内容**（包含图文及音频对齐信息），生成结构化的 Markdown 笔记。

## 核心指令
1.  **严格依据来源**：所有笔记内容必须严格基于下方提供的【课件对齐内容】生成。不要添加文档外的知识，除非是为了解释文档中已提及但未详细说明的术语。
2.  **结构化整理**：将内容组织成有逻辑的章节、子节和列表。
3.  **整合多种信息**：请将"页面"中的文本、公式、要点，与"音频"中的讲解内容有机结合，形成连贯的叙述。
4.  **公式处理**：**所有数学公式请转换为自然的手写书面格式**，具体要求如下：
    *   **分数**：使用 "a/b" 格式，例如用 "θ/360°" 表示比例。
    *   **乘除**：使用 "×" 和 "÷" 符号。
    *   **希腊字母**：直接使用如 "θ", "π" 等符号，或必要时用中文描述（如"角度θ"）。
    *   **上下标**：用自然语言描述，如"地球半径 R_earth" 或写成"R_地球"。
    *   **复杂公式**：可以分步骤用自然语言描述计算过程。
    *   **示例**：将文档中的公式 "C = D \\cdot \\frac{{360}}{{\\theta}}" 转换为 "C = D × 360° ÷ θ"。
5.  **连续性处理**：{continuity_prompt}

## 课件对齐内容 (第{chunk_index}/{total_chunks}部分)
{chunk_context}

## 输出格式要求
1.  使用 Markdown 语法（如 `#` 标题、`-` 列表、`**加粗**` 等）。
2.  **公式必须使用上述"手写书面格式"**，禁止使用 LaTeX 代码块（如 `$$` 或 `\\frac`）。
3.  输出内容应**只包含整理后的知识点本身**，不要包含任何元描述（如"本页介绍了..."）、分析过程、代码注释或提示词本身。
4.  确保内容在章节内部和跨章节之间（如果适用）连贯流畅。
5.  在笔记末尾，请添加一行总结：`<!--SUMMARY: 对本部分核心知识点的1-2句话摘要 -->`

请开始输出笔记内容：
"""

        system_prompt = """你是专业的学术笔记整理专家。

**核心规则：**
1. 只输出最终的 Markdown 笔记内容，禁止输出任何分析过程、思考步骤、审查内容
2. 禁止出现"分析请求"、"起草内容"、"格式化检查"、"构建输出"等元描述
3. 笔记必须直接可用，不包含任何提示词残留

**公式格式（必须严格遵守）：**
- 分数：用 "/" 表示，如 θ/360°、7/360
- 乘除：用 "×" 和 "÷"，不要用 \cdot 或 \frac
- 希腊字母：直接写 θ、α、π，不要用 \theta
- 上下标：用自然语言，如 R_地球、R_sun
- 示例：C = D × 360° ÷ θ

**输出要求：**
- 只输出纯 Markdown 笔记
- 第一行必须是 # 标题
- 最后添加 <!--SUMMARY: 摘要 -->
"""
        return self._call_glm_api(
            prompt=prompt,
            system_prompt=system_prompt
        )

    def _generate_audio_notes(self, audio_context: str, chunk_index: int, total_chunks: int) -> str:
        """
        为音频特有内容生成笔记
        """
        prompt = f"""你是学术笔记整理专家。请根据以下课程讲解音频内容，生成结构化的 Markdown 笔记。

## 核心指令
1. **严格依据来源**：所有内容必须基于提供的音频文本，不要添加外部知识。
2. **结构化整理**：将讲解内容组织成有逻辑的章节，按主题归类（如"课程介绍"、"科学方法"、"哲学思想"、"重要概念解释"等）。
3. **保留关键信息**：保留课程目标、重要概念解释、科学文化特征、历史背景等。
4. **去除闲聊**：过滤掉"大家好"、"谢谢"、"音乐"等开场白和结束语，以及重复的客套话。

## 音频内容 (第{chunk_index}/{total_chunks}部分)
{audio_context}

## 输出格式要求
1. 使用 Markdown 语法（如 `##` 标题、`-` 列表）。
2. 按主题组织内容，不要简单罗列。
3. 保留重要的引用和解释。
4. 在笔记末尾添加：`<!--SUMMARY: 本部分核心内容摘要 -->`

请直接输出笔记内容：
"""

        system_prompt = """你是专业的学术笔记整理专家，擅长将课程讲解音频转换为结构清晰的学习笔记。你会严格依据音频内容，保留关键知识点，去除无关闲聊，生成可直接阅读的Markdown笔记。你会按主题组织内容，而不是简单罗列。"""

        return self._call_glm_api(
            prompt=prompt,
            system_prompt=system_prompt
        )

    def _post_process_formulas(self, text: str) -> str:
        """强制将LaTeX公式转换为自然手写格式"""
        import re

        # 1. 替换分数 \frac{a}{b} -> a/b
        text = re.sub(r'\\frac\{([^}]+)\}\{([^}]+)\}', r'\1/\2', text)

        # 2. 替换乘号
        text = re.sub(r'\\cdot', '×', text)
        text = re.sub(r'\\times', '×', text)

        # 3. 替换希腊字母
        text = re.sub(r'\\theta', 'θ', text)
        text = re.sub(r'\\alpha', 'α', text)
        text = re.sub(r'\\pi', 'π', text)
        text = re.sub(r'\\cos', 'cos', text)
        text = re.sub(r'\\sin', 'sin', text)

        # 4. 移除 $ 符号（但保留内容）
        text = re.sub(r'\$(.*?)\$', r'\1', text)

        # 5. 替换常见的 LaTeX 格式
        text = re.sub(r'\\div', '÷', text)
        text = re.sub(r'^\{([^}]+)\}$', r'\1', text)  # 移除多余的 {}

        # 6. 清理多余的反斜杠
        text = re.sub(r'\\([a-zA-Z]+)', r'\1', text)  # \text -> text

        return text

    def generate_html_mindmap(self, md_content: str, output_path: str) -> None:
        """
        自动生成包含思维导图的 HTML 文件
        修复版：使用 markmap-autoloader 的正确HTML结构
        """
        import html as html_module
        from datetime import datetime

        # 转义内容中的特殊HTML字符，防止破坏HTML结构
        escaped_md = html_module.escape(md_content)

        html_template = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>课程思维导图 - Smart Note</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container { 
            max-width: 1400px; 
            margin: 0 auto; 
            background: white;
            border-radius: 16px;
            padding: 30px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.15);
        }
        h1 { 
            text-align: center; 
            color: #2c3e50; 
            margin-bottom: 24px; 
            padding-bottom: 16px;
            border-bottom: 3px solid #667eea;
            font-size: 28px;
        }
        /* ===== Markmap 必需样式 ===== */
        .markmap {
            position: relative;
            width: 100%;
            min-height: 700px;
            background: #fafbfc;
            border-radius: 12px;
            border: 2px solid #e1e8ed;
            overflow: hidden;
        }
        .markmap > svg {
            width: 100%;
            height: 700px;
            display: block;
        }
        /* ========================== */
        .loading {
            position: absolute;
            top: 50%; left: 50%;
            transform: translate(-50%, -50%);
            color: #667eea;
            font-size: 18px;
            font-weight: 500;
            z-index: 10;
        }
        .loading::after {
            content: "";
            display: block;
            width: 40px; height: 40px;
            margin: 12px auto;
            border: 3px solid #e1e8ed;
            border-top-color: #667eea;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .info-box {
            margin-top: 24px;
            padding: 20px;
            background: linear-gradient(135deg, #f5f7fa 0%, #e8f4fc 100%);
            border-radius: 12px;
            border-left: 4px solid #667eea;
        }
        .info-box h3 { margin-top: 0; color: #2c3e50; font-size: 18px; }
        .info-box ul { margin: 0; padding-left: 20px; }
        .info-box li { margin: 8px 0; color: #555; line-height: 1.6; }
        .footer {
            margin-top: 16px; padding-top: 16px;
            border-top: 1px solid #e1e8ed;
            color: #888; font-size: 13px; text-align: center;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📚 课程思维导图</h1>
        <div class="markmap">
            <div class="loading" id="loading">正在加载思维导图...</div>
            <script type="text/template">
{md_content}
            </script>
        </div>
        <div class="info-box">
            <h3>🎯 使用说明</h3>
            <ul>
                <li><strong>展开/折叠：</strong>点击节点前的圆圈可展开或折叠子节点</li>
                <li><strong>移动视图：</strong>在空白处按住鼠标拖动可移动整个思维导图</li>
                <li><strong>缩放视图：</strong>使用鼠标滚轮可放大/缩小</li>
            </ul>
            <div class="footer">
                <strong>Smart Note</strong> | 生成时间：{timestamp}
            </div>
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/markmap-autoloader@latest"></script>
    <script>
        document.addEventListener("DOMContentLoaded", function() {
            setTimeout(function() {
                var loading = document.getElementById("loading");
                if (loading) loading.style.display = "none";
            }, 1500);
            setTimeout(function() {
                if (!document.querySelector('.markmap svg') && document.getElementById("loading")) {
                    document.getElementById("loading").innerHTML = '加载失败，请检查网络连接';
                }
            }, 5000);
        });
    </script>
</body>
</html>'''

        html_content = html_template.replace('{md_content}', escaped_md)
        html_content = html_content.replace('{timestamp}', datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        print(f"🎨 思维导图 HTML 已生成: {output_path}")

    def _smart_merge(self, chunk_notes: List[str], metadata: Dict) -> str:
        lines = []

        source_name = metadata.get("source_name", "学习笔记")
        lines.append(f"# {source_name}")
        lines.append("")
        lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"> 总页数: {metadata.get('total_pages', 0)}")
        lines.append("")

        for i, note in enumerate(chunk_notes, 1):
            cleaned = re.sub(r'<!--SUMMARY:.*?-->', '', note, flags=re.DOTALL).strip()
            if cleaned:
                lines.append(cleaned)
                lines.append("")

        combined = "\n".join(lines)

        # 如果内容太长，直接返回拼接版本
        if len(combined) > 4000:
            return combined

        # 尝试用 API 整合
        try:
            merge_prompt = f"""请将以下内容整合成一份连贯的学习笔记，去除重复，统一格式：

{combined}

请输出整合后的完整笔记："""

            final = self._call_glm_api(
                prompt=merge_prompt,
                system_prompt="你是文档编辑专家，擅长整合分段内容为连贯的文档。"
            )
            return final
        except:
            return combined

    def generate_markdown_notes(self, alignment_data: Dict,
                                output_dir: str = None,
                                note_style: str = "academic") -> Dict:
        if self.debug_mode:
            print("=" * 60)
            print("📒 智能笔记生成器启动")
            print("=" * 60)

        try:
            pages = alignment_data.get("pages", [])
            audio_only_content = alignment_data.get("audio_only_content", [])
            source_name = alignment_data.get("source_name", "unknown")
            total_pages = len(pages)

            if self.debug_mode:
                print(f"📊 数据处理:")
                print(f"  来源: {source_name}")
                print(f"  总页数: {total_pages}")
                print(f"  音频特有段: {len(audio_only_content)}")

            chunk_size = 3
            page_chunks = self._chunk_pages(pages, chunk_size)

            if self.debug_mode:
                print(f"🔄 分块: 共 {len(page_chunks)} 块页面内容")

            chunk_notes = []
            previous_summary = ""

            # ========== 第一步：处理所有页面内容 ==========
            for i, chunk_pages in enumerate(page_chunks, 1):
                is_last = (i == len(page_chunks))

                if self.debug_mode:
                    print(f"\n  📄 处理第 {i}/{len(page_chunks)} 块页面")

                # 每个请求前都等待（除了第一个）
                if i > 1:
                    wait_time = random.uniform(5,8)
                    print(f"⏳ 等待 {wait_time:.1f} 秒避免限速...")
                    time.sleep(wait_time)

                # 提取页面上下文（不再包含音频特有内容）
                context_text, chunk_meta = self._extract_page_context(chunk_pages)

                if self.debug_mode:
                    print(f"    上下文: {len(context_text)} 字符")

                try:
                    chunk_note_raw = self._generate_chunk_notes(
                        context_text, i, len(page_chunks), previous_summary
                    )
                    chunk_note = self._post_process_formulas(chunk_note_raw)

                    if len(chunk_note) > 0:
                        chunk_notes.append(chunk_note)
                        summary_match = re.search(r'<!--SUMMARY:(.*?)-->', chunk_note, re.DOTALL)
                        if summary_match:
                            previous_summary = summary_match.group(1).strip()[:150]

                        if self.debug_mode:
                            print(f"    ✅ 生成成功: {len(chunk_note)} 字符")

                        # 成功后再等待一段时间，确保不触发限制
                        if not is_last:
                            cool_down = random.uniform(3, 5)
                            print(f"    ❄️ 冷却 {cool_down:.1f} 秒...")
                            time.sleep(cool_down)
                    else:
                        raise Exception("返回空内容")

                except Exception as e:
                    if self.debug_mode:
                        print(f"    ❌ 生成失败: {e}")
                    chunk_notes.append(f"<!-- 第{i}块生成失败: {str(e)} -->")

            # ========== 第二步：单独处理音频特有内容 ==========
            if audio_only_content and len(audio_only_content) > 0:
                print(f"\n🎵 处理音频特有内容 ({len(audio_only_content)} 段)...")

                # 将音频内容分成多块（每块25段，避免过长）
                audio_chunk_size = 25
                audio_chunks = [
                    audio_only_content[i:i+audio_chunk_size]
                    for i in range(0, len(audio_only_content), audio_chunk_size)
                ]

                print(f"  分为 {len(audio_chunks)} 块处理")

                for i, audio_chunk in enumerate(audio_chunks, 1):
                    # 等待避免限速
                    if i > 1 or len(page_chunks) > 0:  # 如果有页面内容，也需要等待
                        wait_time = random.uniform(5,8)
                        print(f"⏳ 等待 {wait_time:.1f} 秒...")
                        time.sleep(wait_time)

                    # 提取音频上下文
                    audio_context = self._extract_audio_context(audio_chunk)

                    if len(audio_context.strip()) == 0:
                        print(f"  ⚠️ 音频块 {i} 无有效内容，跳过")
                        continue

                    if self.debug_mode:
                        print(f"  🎤 处理音频块 {i}/{len(audio_chunks)} ({len(audio_context)} 字符)")

                    try:
                        # 生成音频笔记
                        audio_note_raw = self._generate_audio_notes(
                            audio_context, i, len(audio_chunks)
                        )
                        audio_note = self._post_process_formulas(audio_note_raw)

                        if len(audio_note) > 0:
                            chunk_notes.append(audio_note)
                            if self.debug_mode:
                                print(f"    ✅ 生成成功: {len(audio_note)} 字符")
                        else:
                            raise Exception("返回空内容")

                    except Exception as e:
                        if self.debug_mode:
                            print(f"    ❌ 生成失败: {e}")
                        chunk_notes.append(f"<!-- 音频块{i}生成失败: {str(e)} -->")

            # ========== 第三步：合并所有笔记 ==========
            if self.debug_mode:
                print(f"\n🔄 合并 {len(chunk_notes)} 块笔记...")

            if len(chunk_notes) > 0:
                wait_time = random.uniform(5, 8)
                print(f"⏳ 合并前等待 {wait_time:.1f} 秒...")
                time.sleep(wait_time)

            final_notes = self._smart_merge(chunk_notes, {
                "source_name": source_name,
                "total_pages": total_pages
            })

            if output_dir is None:
                output_dir = Config.get_output_path("notes", alignment_data.get("file_type", "pdf"), source_name)
            os.makedirs(output_dir, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            notes_path = os.path.join(output_dir, f"notes_{source_name}_{timestamp}.md")

            with open(notes_path, 'w', encoding='utf-8') as f:
                f.write(final_notes)

            mindmap_path = notes_path.replace('.md', '_mindmap.html')
            self.generate_html_mindmap(final_notes, mindmap_path)



            result = {
                "success": True,
                "notes_path": notes_path,
                "mindmap_path": mindmap_path,  # 确保这里包含思维导图路径
                "source_name": source_name,
                "markdown_length": len(final_notes),
                "pages_count": total_pages,
                "audio_segments_count": len(audio_only_content),
                "chunks_processed": len(chunk_notes),
                "generated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "model_used": "glm-4-flash-250414",
                "parameters": {
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                    "top_p": self.top_p
                }
            }

            if self.debug_mode:
                print(f"\n✅ 笔记生成完成!")
                print(f"  文件: {notes_path}")
                print(f"  思维导图: {mindmap_path}")
                print(f"  总长度: {result['markdown_length']} 字符")
                print(f"  处理块数: {result['chunks_processed']}")

            return result

        except Exception as e:
            if self.debug_mode:
                print(f"❌ 笔记生成失败: {e}")
                import traceback
                traceback.print_exc()

            return {
                "success": False,
                "error": str(e),
                "generated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

    def generate_notes_from_file(self, alignment_json_path: str,
                                 output_dir: str = None,
                                 note_style: str = "academic") -> Dict:
        if self.debug_mode:
            print(f"📁 加载对齐结果: {alignment_json_path}")

        try:
            with open(alignment_json_path, 'r', encoding='utf-8') as f:
                alignment_data = json.load(f)
            return self.generate_markdown_notes(alignment_data, output_dir, note_style)
        except Exception as e:
            return {"success": False, "error": f"文件加载失败: {str(e)}"}



def generate_notes_for_web(alignment_json_path=None, source_name=None, file_type="pdf", output_dir=None):
    """
    笔记生成函数接口 - 用于调度器调用

    参数：
    alignment_json_path (str): 对齐结果JSON文件路径
    source_name (str): 源文件名
    file_type (str): 文件类型
    output_dir (str): 输出目录

    返回：
    dict: 笔记生成结果
    """
    try:
        generator = NoteGenerator(debug_mode=True)

        # 如果未提供对齐文件路径，尝试自动查找
        if alignment_json_path is None:
            if source_name is None:
                return {"success": False, "error": "需要提供source_name或alignment_json_path"}

            from config import Config
            import glob

            # 查找该源文件的最新对齐结果
            alignment_dir = Config.get_output_path("alignment", file_type, source_name)
            json_files = glob.glob(os.path.join(alignment_dir, "alignment_*.json"))

            if not json_files:
                return {"success": False, "error": f"未找到{source_name}的对齐结果"}

            # 使用最新的对齐文件
            json_files.sort(key=os.path.getmtime, reverse=True)
            alignment_json_path = json_files[0]

        # 生成笔记
        result = generator.generate_notes_from_file(alignment_json_path, output_dir)
        return result

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }




def test_note_generation():
    print("🔧 测试笔记生成...")

    generator = NoteGenerator(debug_mode=True)

    test_file = r"D:\Python in school\try_project\smart_note\output\alignment\pdf\DM_20260415110819_001\alignment_20260417_203153.json"

    if os.path.exists(test_file):
        result = generator.generate_notes_from_file(test_file)
        print(f"\n{'🎉 成功' if result['success'] else '❌ 失败'}: {result.get('notes_path', result.get('error'))}")
    else:
        print(f"⚠️ 文件不存在: {test_file}")



if __name__ == "__main__":
    test_note_generation()