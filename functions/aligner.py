"""
aligner.py
核心对齐模块
使用GLM-4.6V-Flash进行音频与PPT/PDF的多模态对齐
"""

import os
import json
import requests
import time
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Optional
import base64
from config import Config
from ocr_extractor import OCRAnalyzer

# 修复PaddleOCR环境变量
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
os.environ['FLAGS_use_stride_kernel'] = 'True'
os.environ['FLAGS_use_cuda'] = '0'
os.environ['FLAGS_cudnn_deterministic'] = '1'
os.environ['FLAGS_use_mkldnn'] = '0'  # 禁用MKLDNN避免oneDNN错误
os.environ['ONEDNN_VERBOSE'] = '0'


class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


class GLM4VAligner:
    """
    GLM-4.6V-Flash多模态对齐器
    """

    def __init__(self, api_key: str = None, base_url: str = None):
        """
        初始化GLM-4.6V API客户端
        """
        self.api_key = api_key or Config.GLM_API_KEY
        self.base_url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"#base_url or Config.GLM_BASE_URL

        print(f"🔍 配置验证:")
        print(f"  - API密钥是否存在: {'是' if self.api_key else '否'}")
        print(f"  - API密钥前10位: {self.api_key[:10] if self.api_key else '无密钥'}")
        print(f"  - API密钥长度: {len(self.api_key) if self.api_key else 0}")
        print(f"  - API端点: {self.base_url}")


        if not self.api_key:
            raise ValueError("GLM API密钥未设置，请在.env文件中设置GLM_API_KEY")

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        print(f"  - Authorization头: '{self.headers['Authorization']}'")  # 注意两边加了单引号

        # 初始化OCR分析器，如果PaddleOCR失败则自动降级
        self.ocr_analyzer = OCRAnalyzer()

    def encode_image_to_base64(self, image_path: str) -> str:
        """将图片编码为base64字符串"""
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"图片不存在: {image_path}")

        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')

        # ✅ 验证放在 return 之前
        if len(base64_image) < 100:
            print(f"⚠️ 图片 base64 编码异常短: {len(base64_image)} 字符")

        return base64_image

    def load_transcription(self, json_path: str) -> Dict:
        """
        加载音频转写结果
        """
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def clean_json_response(self, response_text: str) -> str:
        """
        移除JSON中的markdown代码块标记，并修复LaTeX公式中的反斜杠问题
        """
        if not response_text:
            return response_text

        # 1. 移除开头的 ```json
        if response_text.startswith('```json'):
            response_text = response_text[7:]

        # 2. 移除结尾的 ```
        if response_text.rstrip().endswith('```'):
            response_text = response_text.rstrip()[:-3]

        # 3. 修复 formulas 数组中的 LaTeX 反斜杠问题
        import re

        # 找到 formulas 数组内容
        formulas_match = re.search(r'"formulas":\s*\[(.*?)\]', response_text, re.DOTALL)
        if formulas_match:
            formulas_content = formulas_match.group(1)
            # 替换所有 LaTeX 命令中的 \ 为 \\（JSON 合法转义）
            # 例如：\frac → \\frac, \cos → \\cos
            # 但注意不要破坏已有的 $
            # 我们只处理非 $ 包裹的 \，或者确保公式整体安全
            # 更安全的方式：把整个公式用双引号包裹，并确保 \ 被转义
            # 但这里我们简单粗暴：把所有 \ 替换成 \\
            # 同时，把 \( 和 \) 替换成 $，避免后续解析错误
            fixed_formulas = formulas_content.replace(r'\\(', '$').replace(r'\\)', '$')
            fixed_formulas = fixed_formulas.replace('\\', '\\\\')  # 转义所有反斜杠
            # 重新组装
            response_text = response_text[:formulas_match.start(1)] + fixed_formulas + response_text[
                                                                                       formulas_match.end(1):]

        return response_text.strip()

    def analyze_slide_with_glm4v(self, image_path: str, ocr_text: str = "") -> Dict:
        """
        使用GLM-4.6V分析单张幻灯片
        """
        try:
            base64_image = self.encode_image_to_base64(image_path)

            # 1. 清理OCR文本，移除可能的问题字符
            clean_ocr_text = ocr_text[:500] if ocr_text else ""
            # 移除控制字符和多余空白
            clean_ocr_text = "".join(char for char in clean_ocr_text if char.isprintable() or char in "\n\t")
            clean_ocr_text = " ".join(clean_ocr_text.split())  # 标准化空格

            # 2. 构建简洁的单行提示词
            combined_prompt = (
                "你是一个专业的数学和科学文档分析助手。请分析用户提供的幻灯片图片，特别注意其中的数学公式、方程和科学符号。"
                "请生成结构化笔记，包含以下内容：\n"
                "1. 页面标题（简洁准确）\n"
                "2. 核心知识要点（包括完整的数学公式，用LaTeX格式表示，如：$E = mc^2$）\n"
                "3. 关键公式列表（如果有数学公式，请单独提取并以LaTeX格式列出）\n"
                "4. 关键图表说明（如有图表/公式/示意图则详细描述）\n"
                "5. 知识点分类（如：数学、物理、化学、天文学、几何学等）\n"
                "6. 本页摘要（50字以内概括，确保包含主要公式的关键信息）\n\n"
                "重要要求：\n"
                "- 对于数学公式，必须保持其完整性，使用标准的LaTeX语法\n"
                "- 数学公式用 $ 符号包裹，例如：$E = mc^2$，不要使用 \\( 和 \\)\n"
                "- LaTeX命令使用单反斜杠，例如：\\frac, \\cos, \\alpha\n"
                "- 确保公式在JSON中格式正确，不会破坏JSON解析\n"
                "- 不要简化或省略公式中的任何符号\n"
                "- 如果公式是核心内容，请确保在main_points和formulas中都包含\n"
                "- 对于复杂的多行公式，使用$$...$$环境\n\n"
                f"参考OCR文本（可能不准确，特别是公式部分）：{clean_ocr_text}\n\n"
                '''请返回如下格式的JSON：
                {{
                  "slide_title": "页面标题",
                  "main_points": ["要点1", "要点2"],
                  "formulas": ["$公式1$", "$公式2$"],
                  "key_diagrams": "图表说明",
                  "knowledge_category": "知识点分类",
                  "slide_summary": "页面摘要"
                }}'''
                "注意：formulas字段是专门存储数学公式的数组，确保公式完整且格式正确。"
                "公式示例：$\\frac{a}{b}$, $\\cos(\\alpha)$, $E = mc^2$"
            )

            # 3. 使用与测试连接相同的API格式
            payload = {
                "model": "glm-4v-flash",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": combined_prompt
                            },
                            {
                                "type": "image_url",  # ✅ 必须是 image_url
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"  # ✅ data URI 格式
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 1000,
            }

            # 4. 添加详细的调试信息
            print(f"🔍 正在分析: {Path(image_path).name}")
            print(f"  - 提示词长度: {len(combined_prompt)} 字符")
            print(f"  - 图片base64长度: {len(base64_image)} 字符")
            print(f"  - API端点: {self.base_url}")

            # 5. 发送请求
            response = requests.post(
                self.base_url,
                headers=self.headers,
                json=payload,
                timeout=60
            )

            # 6. 详细的错误处理
            if response.status_code != 200:
                print(f"❌ API调用失败: {response.status_code}")
                print(f"❌ 错误详情: {response.text}")
                print(f"❌ 请求URL: {self.base_url}")
                print(f"❌ 请求头: {dict(self.headers)}")
                print(f"❌ 请求payload结构（简化）:")
                debug_payload = payload.copy()
                # 隐藏大段的base64数据以便查看
                content_item = debug_payload["messages"][0]["content"][1]
                if content_item.get("type") == "image_url" and "image_url" in content_item:
                    img_url = content_item["image_url"]["url"]
                    if len(img_url) > 100:
                        content_item["image_url"]["url"] = img_url[:100] + "...[截断]"
                import json as json_lib
                print(json_lib.dumps(debug_payload, ensure_ascii=False, indent=2)[:500] + "...")

                raise Exception(f"API调用失败: {response.status_code}")

            result = response.json()
            content = result["choices"][0]["message"]["content"]

            # ======================= 新增：JSON清理 =======================
            # 添加调试信息
            print(f"  📥 原始响应长度: {len(content)} 字符")
            print(f"  📥 原始响应前200字: {content[:200]}")

            # 调用JSON清理函数
            cleaned_content = self.clean_json_response(content)
            print(f"  🔧 清理后响应: {cleaned_content[:200]}")

            # 使用清理后的内容
            content = cleaned_content

            # 清理可能的非法字符
            content = content.strip()
            # 移除可能的 BOM 头
            if content.startswith('\ufeff'):
                content = content[1:]

            # 尝试解析 JSON，如果失败则使用默认结果
            try:
                analysis_result = json.loads(content)
            except json.JSONDecodeError as e:
                print(f"⚠️ JSON 解析失败，尝试修复: {e}")
                # 添加更详细的错误信息
                print(f"  🔧 错误位置: {e.pos}, 行: {e.lineno}, 列: {e.colno}")
                print(f"  🔧 错误内容片段: {content[max(0, e.pos - 30):min(len(content), e.pos + 30)]}")
                # 尝试修复常见的 JSON 格式问题
                try:
                    # 使用 ast 库进行更安全的修复
                    import ast

                    # 将字符串转为Python对象
                    try:
                        obj = ast.literal_eval(content)
                        analysis_result = obj
                    except (SyntaxError, ValueError):
                        # 如果不行，尝试更简单的方法
                        # 移除formulas数组中的反斜杠问题
                        if '"formulas":' in content:
                            # 修复不完整的formulas数组
                            import re
                            # 修复公式以"$\frac{"开头但不完整的问题
                            fixed_content = re.sub(r'"formulas": \[[^\]]*\\$', '"formulas": []', content)
                            fixed_content = re.sub(r'"formulas": \[\s*"[^"]*\\\\?\("', '"formulas": ["$公式$"]',
                                                   fixed_content)

                            analysis_result = json.loads(fixed_content)
                        else:
                            raise ValueError("无法修复")

                except Exception as fix_e:
                    print(f"❌ 无法修复 JSON，使用默认结果: {fix_e}")
                    print(f"原始内容前300字: {content[:300]}")

                    # 返回默认结果，但尝试从原始内容中提取一些信息
                    slide_title = "第" + Path(image_path).stem + "页"
                    slide_summary = clean_ocr_text[:200] if clean_ocr_text else "解析失败"

                    # 尝试从原始响应中提取标题
                    title_match = re.search(r'"slide_title":\s*"([^"]*)"', content)
                    if title_match:
                        slide_title = title_match.group(1)

                    # 返回默认结果
                    analysis_result = {
                        "slide_title": slide_title,
                        "main_points": ["JSON解析失败，使用OCR文本"],
                        "formulas": [],
                        "key_diagrams": "",
                        "knowledge_category": "unknown",
                        "slide_summary": slide_summary
                    }

            return analysis_result

        except Exception as e:
            print(f"❌ 幻灯片分析失败: {e}")
            import traceback
            traceback.print_exc()  # 打印完整的错误栈

            # 返回默认结果
            return {
                "slide_title": f"第{Path(image_path).stem}页",
                "main_points": [clean_ocr_text[:100] + "..." if clean_ocr_text else "无内容"],
                "formulas": [],  # 确保有这个字段
                "key_diagrams": "",
                "knowledge_category": "text_content",
                "slide_summary": clean_ocr_text[:200] + "..." if clean_ocr_text else "无内容"
            }

    def text_similarity(self, text1: str, text2: str) -> float:
        """
        计算中文文本相似度（使用 jieba 分词）
        """
        import jieba

        if not text1 or not text2:
            return 0.0

        # 用 jieba 分词，并过滤停用词
        stop_words = {'，', '。', '、', '；', '：', '"', '"', ''', ''', '（', '）', ' ', '\n', '\t', '的', '是', '了', '在',
                      '和', '与', '为', '对', '等'}

        words1 = set(w for w in jieba.lcut(text1) if w not in stop_words and len(w) > 1)
        words2 = set(w for w in jieba.lcut(text2) if w not in stop_words and len(w) > 1)

        if not words1 or not words2:
            return 0.0

        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))

        return intersection / union if union > 0 else 0.0

    def enhance_ocr_for_formulas(self, ocr_text: str) -> str:
        import re

        if not ocr_text:
            return ""

        # 修复常见的数学符号识别问题
        replacements = [
            # 希腊字母修复
            (
            r'\b(alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|lambda|mu|nu|xi|omicron|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega)\b',
            lambda m: f"\\{m.group(1)}"),  # alpha -> \alpha

            # 分数修复
            (r'(\d+)/(\d+)', r'\\frac{\1}{\2}'),  # 1/2 -> \frac{1}{2}

            # 修复上下标
            (r'(\w+)\^(\w+)', r'\1^{\2}'),  # x^2 -> x^{2}
            (r'(\w+)_(\w+)', r'\1_{\2}'),  # x_i -> x_{i}

            # 修复数学运算符
            (r'\\\*', r'*'),  # \* -> *
            (r'<=', r'≤'),
            (r'>=', r'≥'),
            (r'!=', r'≠'),

            # 修复特殊字符
            (r'\\u0007', r'\\'),  # 修复非法Unicode
        ]

        enhanced_text = ocr_text

        for pattern, replacement in replacements:
            if callable(replacement):
                enhanced_text = re.sub(pattern, replacement, enhanced_text, flags=re.IGNORECASE)
            else:
                enhanced_text = re.sub(pattern, replacement, enhanced_text)

        return enhanced_text



    def calculate_similarity_matrix(self, ocr_pages: List[Dict], audio_segments: List[Dict]) -> np.ndarray:
        """
        计算OCR页面与音频段落的相似度矩阵
        """
        n_pages = len(ocr_pages)
        n_segments = len(audio_segments)
        similarity_matrix = np.zeros((n_pages, n_segments))

        for i, page in enumerate(ocr_pages):
            page_text = page.get("ocr_text", "")
            for j, segment in enumerate(audio_segments):
                segment_text = segment.get("text", "")
                if page_text.strip() and segment_text.strip():
                    similarity = self.text_similarity(page_text, segment_text)
                    similarity_matrix[i, j] = similarity
                else:
                    similarity_matrix[i, j] = 0.0

        return similarity_matrix

    def find_optimal_alignment(self, similarity_matrix: np.ndarray) -> List[Dict]:
        """
        使用动态规划找到最优对齐路径
        """
        n_pages, n_segments = similarity_matrix.shape

        if n_pages == 0 or n_segments == 0:
            return []

        dp = np.zeros((n_pages + 1, n_segments + 1))
        path = np.zeros((n_pages + 1, n_segments + 1, 2), dtype=int)

        for i in range(1, n_pages + 1):
            dp[i][0] = dp[i - 1][0] - 0.5
            path[i][0] = [i - 1, 0]

        for j in range(1, n_segments + 1):
            dp[0][j] = dp[0][j - 1] - 0.3
            path[0][j] = [0, j - 1]

        for i in range(1, n_pages + 1):
            for j in range(1, n_segments + 1):
                options = [
                    (dp[i - 1][j - 1] + similarity_matrix[i - 1][j - 1], 0),
                    (dp[i - 1][j] - 0.5, 1),
                    (dp[i][j - 1] - 0.3, 2)
                ]

                best_score, best_move = max(options, key=lambda x: x[0])
                dp[i][j] = best_score

                if best_move == 0:
                    path[i][j] = [i - 1, j - 1]
                elif best_move == 1:
                    path[i][j] = [i - 1, j]
                else:
                    path[i][j] = [i, j - 1]

        alignment = []
        i, j = n_pages, n_segments

        while i > 0 or j > 0:
            prev_i, prev_j = path[i][j]

            if i > prev_i and j > prev_j:
                alignment.append({
                    "page_index": i - 1,
                    "segment_index": j - 1,
                    "similarity": similarity_matrix[i - 1][j - 1],
                    "type": "matched"
                })
            elif i > prev_i:
                alignment.append({
                    "page_index": i - 1,
                    "segment_index": None,
                    "similarity": 0,
                    "type": "visual_only"
                })
            else:
                alignment.append({
                    "page_index": None,
                    "segment_index": j - 1,
                    "similarity": 0,
                    "type": "audio_only"
                })

            i, j = prev_i, prev_j

        alignment.reverse()
        return alignment

    def align_content(self, ocr_results: Dict, transcription_data: Dict,
                      file_type: str = "ppt") -> Dict:
        """
        执行内容对齐
        """
        print(f"🔍 开始内容对齐...")

        ocr_pages = ocr_results.get("pages", [])
        audio_segments = transcription_data.get("segments", [])

        print(f"📊 对齐规模:")
        print(f"  - PPT/PDF页数: {len(ocr_pages)}")
        print(f"  - 音频分段数: {len(audio_segments)}")

        if not ocr_pages or not audio_segments:
            print("⚠️ 警告: OCR结果或音频转写为空，返回默认对齐")
            return self._create_default_alignment(ocr_pages, audio_segments, file_type)

        print("📈 计算相似度矩阵...")
        similarity_matrix = self.calculate_similarity_matrix(ocr_pages, audio_segments)

        print("🔄 寻找最优对齐路径...")
        alignment_path = self.find_optimal_alignment(similarity_matrix)

        print("🤖 对图表页进行视觉分析...")
        aligned_pages = []
        vision_only_pages = []
        audio_only_segments = []

        # 在align_content方法中，找到对齐页面的循环部分
        for alignment in alignment_path:
            if alignment["type"] == "matched":
                page_idx = alignment["page_index"]
                segment_idx = alignment["segment_index"]

                page_data = ocr_pages[page_idx]
                segment_data = audio_segments[segment_idx]

                # 在分析前先增强OCR文本中的公式
                enhanced_ocr = self.enhance_ocr_for_formulas(page_data.get("ocr_text", ""))
                page_data["ocr_text"] = enhanced_ocr  # 更新OCR文本

                print(f"  📄 分析第{page_data['page_number']}页...")
                vision_analysis = self.analyze_slide_with_glm4v(
                    page_data["image_path"],
                    page_data["ocr_text"]  # 使用增强后的文本
                )
                time.sleep(1.0)  # 避免请求过快

                aligned_page = {
                    "page_number": page_data["page_number"],
                    "slide_title": vision_analysis.get("slide_title", ""),
                    "main_points": vision_analysis.get("main_points", []),
                    "formulas": vision_analysis.get("formulas", []),  # 新增字段
                    "key_diagrams": vision_analysis.get("key_diagrams", ""),
                    "knowledge_category": vision_analysis.get("knowledge_category", ""),
                    "slide_summary": vision_analysis.get("slide_summary", ""),
                    "ocr_text": page_data.get("ocr_text", ""),
                    "enhanced_ocr_text": enhanced_ocr,  # 保存增强后的文本
                    "image_path": page_data.get("image_path", ""),
                    "audio_segments": [segment_data],
                    "similarity_score": alignment["similarity"],
                    "content_type": "matched"
                }
                aligned_pages.append(aligned_page)

            elif alignment["type"] == "visual_only":
                page_idx = alignment["page_index"]
                page_data = ocr_pages[page_idx]

                vision_page = {
                    "page_number": page_data["page_number"],
                    "slide_title": f"第{page_data['page_number']}页（视觉特有）",
                    "main_points": page_data.get("text_blocks", [])[:5],
                    "key_diagrams": "",
                    "knowledge_category": "visual_content",
                    "slide_summary": page_data.get("ocr_text", "")[:200] + "..." if page_data.get("ocr_text") else "无内容",
                    "ocr_text": page_data.get("ocr_text", ""),
                    "image_path": page_data.get("image_path", ""),
                    "audio_segments": [],
                    "similarity_score": 0,
                    "content_type": "visual_only"
                }
                vision_only_pages.append(vision_page)

            elif alignment["type"] == "audio_only":
                segment_idx = alignment["segment_index"]
                segment_data = audio_segments[segment_idx]

                audio_only_segments.append({
                    "segment_number": segment_idx + 1,
                    "start": segment_data.get("start", ""),
                    "end": segment_data.get("end", ""),
                    "text": segment_data.get("text", ""),
                    "content_type": "audio_only"
                })

        all_pages = aligned_pages + vision_only_pages
        all_pages.sort(key=lambda x: x["page_number"])

        alignment_result = {
            "alignment_success": True,
            "alignment_strategy": "dynamic_content_based",
            "file_type": file_type,
            "source_name": ocr_results.get("source_name", ""),
            "total_pages": len(ocr_pages),
            "total_audio_segments": len(audio_segments),
            "matched_pages": len(aligned_pages),
            "visual_only_pages": len(vision_only_pages),
            "audio_only_segments": len(audio_only_segments),
            "pages": all_pages,
            "audio_only_content": audio_only_segments,
            "transcription_summary": transcription_data.get("full_text", "")[:500] + "..." if transcription_data.get("full_text") else "无转写内容"
        }

        return alignment_result

    def _create_default_alignment(self, ocr_pages, audio_segments, file_type):
        """创建默认对齐结果（当OCR失败时使用）"""
        all_pages = []
        audio_only_segments = []

        for i, page in enumerate(ocr_pages):
            all_pages.append({
                "page_number": page.get("page_number", i + 1),
                "slide_title": f"第{page.get('page_number', i + 1)}页",
                "main_points": ["无OCR文本，使用默认匹配"],
                "key_diagrams": "",
                "knowledge_category": "unknown",
                "slide_summary": "OCR提取失败，无法提供详细内容",
                "ocr_text": page.get("ocr_text", ""),
                "image_path": page.get("image_path", ""),
                "audio_segments": audio_segments[i:i + 1] if i < len(audio_segments) else [],
                "similarity_score": 0.1,
                "content_type": "matched"
            })

        for j in range(len(all_pages), len(audio_segments)):
            if j < len(audio_segments):
                segment = audio_segments[j]
                audio_only_segments.append({
                    "segment_number": j + 1,
                    "start": segment.get("start", ""),
                    "end": segment.get("end", ""),
                    "text": segment.get("text", ""),
                    "content_type": "audio_only"
                })

        return {
            "alignment_success": True,
            "alignment_strategy": "default_fallback",
            "file_type": file_type,
            "source_name": "default",
            "total_pages": len(ocr_pages),
            "total_audio_segments": len(audio_segments),
            "matched_pages": len(ocr_pages),
            "visual_only_pages": 0,
            "audio_only_segments": len(audio_only_segments),
            "pages": all_pages,
            "audio_only_content": audio_only_segments,
            "transcription_summary": "使用默认对齐策略"
        }

    def save_alignment_results(self, alignment_data: Dict, file_type: str = "ppt") -> str:
        """
        保存对齐结果
        """
        source_name = alignment_data.get("source_name", "unknown")
        output_dir = Config.get_output_path("alignment", file_type, source_name)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_file = Path(output_dir) / f"alignment_{timestamp}.json"

        # ✅ 加这行：打印完整绝对路径
        abs_path = output_file.resolve()
        print(f"🔍 实际保存路径: {abs_path}")

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(alignment_data, f, cls=NumpyEncoder, ensure_ascii=False, indent=2)

        print(f"✅ 对齐结果已保存: {output_file}")
        return str(output_file)

    def process_alignment_pipeline(self, image_dir: str, transcription_json: str,
                                   file_type: str = "ppt") -> Dict:
        """
        完整对齐处理流程
        """
        print("=" * 50)
        print("🤖 智能对齐处理流程")
        print("=" * 50)

        print("\n📄 阶段1: OCR文本提取")
        try:
            ocr_result = self.ocr_analyzer.analyze_image_folder(image_dir, file_type)
            if not ocr_result["success"]:
                print("⚠️ OCR部分失败，继续使用默认值...")
                ocr_result = self.ocr_analyzer._get_default_ocr_result(image_dir, file_type)
        except Exception as e:
            print(f"⚠️ OCR处理异常: {e}，使用默认OCR结果")
            ocr_result = self.ocr_analyzer._get_default_ocr_result(image_dir, file_type)

        print("\n🎵 阶段2: 加载音频转写")
        try:
            transcription_data = self.load_transcription(transcription_json)
        except Exception as e:
            print(f"❌ 加载音频转写失败: {e}")
            return {"success": False, "error": f"音频转写加载失败: {str(e)}"}

        print("\n🔗 阶段3: 内容对齐")
        alignment_data = self.align_content(
            ocr_result["ocr_results"],
            transcription_data,
            file_type
        )

        print("\n💾 阶段4: 保存结果")
        output_file = self.save_alignment_results(alignment_data, file_type)

        print("\n" + "=" * 50)
        print("🎉 对齐处理完成!")
        print("=" * 50)
        print(f"📊 处理统计:")
        print(f"  - 总页数: {alignment_data['total_pages']}")
        print(f"  - 音频段数: {alignment_data['total_audio_segments']}")
        print(f"  - 匹配页数: {alignment_data['matched_pages']}")
        print(f"  - 视觉特有页: {alignment_data['visual_only_pages']}")
        print(f"  - 音频特有段: {alignment_data['audio_only_segments']}")
        print(f"  - 输出文件: {output_file}")

        return {
            "success": True,
            "input_image_dir": image_dir,
            "input_transcription": transcription_json,
            "output_file": output_file,
            "alignment_data": alignment_data
        }




def align_audio_with_images(image_dir, transcription_json, file_type="auto"):
    """
    对齐函数接口 - 用于调度器调用

    参数：
    image_dir (str): 图片目录路径
    transcription_json (str): 音频转写JSON文件路径
    file_type (str): 文件类型

    返回：
    dict: 对齐处理结果
    """
    try:
        aligner = GLM4VAligner()
        result = aligner.process_alignment_pipeline(
            image_dir,
            transcription_json,
            file_type
        )
        return result
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def main():
    print("🚀 main() 开始执行")
    from config import Config

    # 加调试
    print("🔍 正在验证配置...")
    is_valid = Config.validate_config()
    print(f"   验证结果: {is_valid}")

    if not is_valid:
        print("❌ 配置验证失败，请检查.env文件")
        print(f"   GLM_API_KEY: {'有' if Config.GLM_API_KEY else '无'}")
        return

    import sys
    import os
    from pathlib import Path

    # 默认配置
    DEFAULT_IMAGE_DIR = r"D:\Python in school\try_project\smart_note\output\pdf\DM_20260415110819_001"
    DEFAULT_TRANSCRIPTION = r"D:\Python in school\try_project\smart_note\output\sound\物理学史_中国大学MOOC_慕课_transcript.json"

    test_image_dir = None
    test_transcription = None
    test_file_type = None  # 不硬编码，改为推断

    # ========== 参数处理 ==========
    if len(sys.argv) >= 3:
        test_image_dir = sys.argv[1]
        test_transcription = sys.argv[2]
        print("📥 使用命令行传入的参数")

    elif len(sys.argv) == 2 and sys.argv[1] == "test":
        print("🧪 测试模式")
        test_image_dir = DEFAULT_IMAGE_DIR
        test_transcription = DEFAULT_TRANSCRIPTION

    elif len(sys.argv) == 1:
        print("⚙️ 开发模式：使用默认路径")
        test_image_dir = DEFAULT_IMAGE_DIR
        test_transcription = DEFAULT_TRANSCRIPTION

    else:
        print("用法: python aligner.py [图片目录 音频JSON | test]")
        return

    # ========== 智能推断文件类型 ==========
    def smart_infer_file_type(image_dir: str) -> str:
        """从图片目录路径智能推断文件类型"""
        if not image_dir:
            return "pdf"  # 默认

        image_dir_lower = image_dir.lower()

        # 优先级1：检查路径中是否包含特定模式
        if r"output\pdf" in image_dir_lower or "output/pdf" in image_dir_lower:
            return "pdf"
        elif r"output\ppt" in image_dir_lower or "output/ppt" in image_dir_lower:
            return "ppt"

        # 优先级2：检查路径中的关键词
        path_parts = Path(image_dir).parts
        for part in path_parts:
            part_lower = part.lower()
            if "pdf" in part_lower:
                return "pdf"
            elif "ppt" in part_lower or "pptx" in part_lower or "powerpoint" in part_lower:
                return "ppt"

        # 优先级3：检查父目录名称
        parent_dir = Path(image_dir).parent.name.lower()
        if "pdf" in parent_dir:
            return "pdf"
        elif "ppt" in parent_dir or "pptx" in parent_dir:
            return "ppt"

        # 默认返回 pdf
        return "pdf"

    # 推断文件类型
    test_file_type = smart_infer_file_type(test_image_dir)
    print(f"📁 推断文件类型: {test_file_type} (从路径: {test_image_dir})")

    # ========== 执行对齐处理 ==========
    if not os.path.exists(test_image_dir):
        print(f"❌ 图片目录不存在: {test_image_dir}")
        return

    if not os.path.exists(test_transcription):
        print(f"❌ 音频转写文件不存在: {test_transcription}")
        return

    print("=" * 50)
    print("🤖 开始对齐处理")
    print(f"  - 图片: {test_image_dir}")
    print(f"  - 音频: {test_transcription}")
    print(f"  - 类型: {test_file_type}")
    print("=" * 50)

    aligner = GLM4VAligner()
    result = aligner.process_alignment_pipeline(
        test_image_dir,
        test_transcription,
        test_file_type
    )

    if result["success"]:
        print(f"\n✅ 完成！输出: {result['output_file']}")
    else:
        print(f"\n❌ 失败: {result.get('error')}")



if __name__ == "__main__":
    main()