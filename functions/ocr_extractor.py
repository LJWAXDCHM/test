"""
ocr_extractor.py
使用EasyOCR的文本提取模块
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Any
from config import Config


class OCRAnalyzer:
    """
    OCR分析器
    使用EasyOCR从图片中提取文字
    """

    def __init__(self, ocr_engine: str = None, lang: List[str] = None):
        """
        初始化OCR分析器
        """
        self.ocr_engine = ocr_engine or Config.OCR_ENGINE
        self.lang = lang or Config.OCR_LANG
        self.engine = self._init_easyocr()

    def _init_easyocr(self):
        """
        初始化EasyOCR引擎
        """
        try:
            import easyocr
            print("正在加载EasyOCR引擎...")
            # EasyOCR自动下载模型，首次使用可能需要一些时间
            reader = easyocr.Reader(self.lang, gpu=True)  # gpu=False 使用CPU
            print("✅ EasyOCR初始化成功")
            return reader
        except ImportError as e:
            print("❌ 未安装EasyOCR，请运行: pip install easyocr")
            raise
        except Exception as e:
            print(f"⚠️ EasyOCR初始化失败: {e}")
            raise

    def extract_text_from_image(self, image_path: str) -> Dict:
        """
        从单张图片中提取文字
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"图片文件不存在: {image_path}")

        print(f"📄 提取文字: {Path(image_path).name}")

        try:
            # 调用EasyOCR识别
            result = self.engine.readtext(
                image_path,
                detail=1,  # 返回详细信息
                paragraph=True,  # 合并为段落
                batch_size=1,  # 单张图片处理
                workers=0,  # 不使用多线程
                min_size=5  # 最小文字尺寸
            )

            text_blocks = []
            full_text = ""

            # 修复：安全处理识别结果
            if result is None:
                result = []

            for detection in result:
                try:
                    # 安全访问列表元素
                    if isinstance(detection, (list, tuple)) and len(detection) >= 2:
                        text = detection[1]  # 文本内容
                        confidence = detection[2] if len(detection) > 2 else 1.0  # 安全获取置信度

                        if text and isinstance(text, str) and text.strip():
                            # 检查置信度
                            if confidence > 0.1:  # 过滤低置信度结果
                                text_blocks.append(str(text).strip())
                                full_text += str(text).strip() + "\n"
                            else:
                                # 低置信度文本，但仍然保留
                                text_blocks.append(str(text).strip() + f" [置信度:{confidence:.2f}]")
                                full_text += str(text).strip() + "\n"
                except Exception as e:
                    print(f"⚠️ 处理OCR结果时出错: {e}")
                    continue  # 跳过当前检测结果，继续处理下一个

            # 如果没有提取到任何文字
            if not text_blocks:
                print(f"ℹ️ 图片{Path(image_path).name}未检测到文字")
                return {
                    "text_blocks": [],
                    "full_text": "未检测到文字",
                    "has_chart": True  # 没有文字可能是图表页
                }

            return {
                "text_blocks": text_blocks,
                "full_text": full_text.strip(),
                "has_chart": self._detect_chart(text_blocks)
            }

        except Exception as e:
            print(f"❌ EasyOCR调用失败: {e}")
            # 返回错误信息
            return {
                "text_blocks": [],
                "full_text": f"OCR失败: {str(e)[:100]}",
                "has_chart": False
            }
    def _detect_chart(self, text_blocks: List[str]) -> bool:
        """
        检测是否为图表页
        """
        if not text_blocks:
            return True  # 没有文字，可能是纯图表页

        chart_keywords = ['图', '表', '图表', '图示', '图片', 'figure', 'table', 'chart', 'diagram']
        for block in text_blocks:
            block_lower = block.lower()
            for keyword in chart_keywords:
                if keyword in block_lower:
                    return True

        # 如果文字很少，可能也是图表页
        total_chars = sum(len(block) for block in text_blocks)
        if total_chars < 50:
            return True

        return False

    def analyze_image_folder(self, image_dir: str, file_type: str = "ppt") -> Dict:
        """
        分析整个图片文件夹
        """
        image_dir_path = Path(image_dir)
        if not image_dir_path.exists():
            raise FileNotFoundError(f"图片目录不存在: {image_dir}")

        # 获取排序后的图片文件
        image_files = sorted(
            [f for f in image_dir_path.iterdir()
             if f.suffix.lower() in {'.jpg', '.jpeg', '.png', '.bmp', '.gif'}],
            key=lambda x: x.name.lower()
        )

        if not image_files:
            raise ValueError(f"图片目录为空: {image_dir}")

        print(f"🔍 开始分析图片文件夹: {image_dir}")
        print(f"📊 图片数量: {len(image_files)}")

        ocr_results = []
        needs_vision_pages = []
        successful_ocr = 0
        failed_ocr = 0

        for page_num, img_path in enumerate(image_files):
            print(f"  处理第 {page_num + 1}/{len(image_files)} 页: {img_path.name}")

            try:
                ocr_result = self.extract_text_from_image(str(img_path))

                if ocr_result["full_text"] and not ocr_result["full_text"].startswith("OCR失败"):
                    successful_ocr += 1
                else:
                    failed_ocr += 1

                page_data = {
                    "page_number": page_num + 1,
                    "image_path": str(img_path),
                    "ocr_text": ocr_result["full_text"],
                    "text_blocks": ocr_result["text_blocks"],
                    "has_chart": ocr_result["has_chart"],
                    "needs_vision_analysis": ocr_result["has_chart"],
                    "ocr_success": ocr_result["full_text"] and not ocr_result["full_text"].startswith("OCR失败")
                }

                ocr_results.append(page_data)

                if ocr_result["has_chart"]:
                    needs_vision_pages.append(page_num + 1)

            except Exception as e:
                print(f"⚠️ 处理图片{img_path.name}时出错: {e}")
                failed_ocr += 1
                page_data = {
                    "page_number": page_num + 1,
                    "image_path": str(img_path),
                    "ocr_text": f"OCR处理失败: {str(e)[:100]}",
                    "text_blocks": [f"错误: {str(e)[:50]}"],
                    "has_chart": False,
                    "needs_vision_analysis": False,
                    "ocr_success": False
                }
                ocr_results.append(page_data)

        # 保存OCR结果
        source_name = image_dir_path.name
        output_dir = Config.get_output_path("ocr", file_type, source_name)
        output_file = Path(output_dir) / f"{source_name}_ocr.json"

        result_data = {
            "source_type": file_type,
            "source_name": source_name,
            "image_dir": str(image_dir),
            "total_pages": len(image_files),
            "successful_ocr_pages": successful_ocr,
            "failed_ocr_pages": failed_ocr,
            "chart_pages": needs_vision_pages,
            "ocr_engine_used": "easyocr",
            "pages": ocr_results
        }

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)

        print(f"✅ OCR分析完成!")
        print(f"📊 统计信息:")
        print(f"  - 总页数: {len(image_files)}")
        print(f"  - 成功OCR页数: {successful_ocr}")
        print(f"  - 失败OCR页数: {failed_ocr}")
        print(f"  - 图表页数: {len(needs_vision_pages)}")
        print(f"  - 输出文件: {output_file}")

        return {
            "success": True,
            "input_dir": str(image_dir),
            "output_file": str(output_file),
            "ocr_results": result_data,
            "chart_pages": needs_vision_pages
        }


def process_ocr_for_alignment(image_dir: str, file_type: str = "ppt"):
    """
    为对齐处理准备OCR数据
    """
    analyzer = OCRAnalyzer()
    return analyzer.analyze_image_folder(image_dir, file_type)


# 在文件末尾添加以下函数
def extract_ocr_from_images(image_dir, file_type="auto"):
    """
    OCR提取函数，用于网页调用

    参数：
    image_dir (str): 图片目录路径
    file_type (str): 文件类型，可选："auto"（自动检测）、"ppt"、"pdf"

    返回：
    dict: 包含OCR提取结果的信息
    """
    # 如果未指定文件类型，尝试从路径自动推断
    if file_type == "auto":
        if "ppt" in image_dir.lower():
            file_type = "ppt"
        elif "pdf" in image_dir.lower():
            file_type = "pdf"
        else:
            file_type = "unknown"  # 默认类型

    try:
        analyzer = OCRAnalyzer()
        result = analyzer.analyze_image_folder(image_dir, file_type)
        return result
    except Exception as e:
        return {
            "success": False,
            "input_dir": image_dir,
            "error": str(e)
        }


def process_images_for_ocr(image_paths, file_type="auto"):
    """
    处理单个或多个图片的OCR提取

    参数：
    image_paths (str or list): 单个图片路径或图片路径列表
    file_type (str): 文件类型

    返回：
    dict: OCR提取结果
    """
    from pathlib import Path

    if isinstance(image_paths, str):
        # 单个图片路径
        if os.path.isfile(image_paths):
            # 处理单张图片
            analyzer = OCRAnalyzer()
            ocr_result = analyzer.extract_text_from_image(image_paths)

            # 创建输出目录
            img_name = Path(image_paths).stem
            output_dir = Config.get_output_path("ocr", file_type, "single_images")
            output_file = Path(output_dir) / f"{img_name}_ocr.json"

            # 保存结果
            result_data = {
                "source_type": file_type,
                "source_name": img_name,
                "image_path": image_paths,
                "ocr_text": ocr_result.get("full_text", ""),
                "text_blocks": ocr_result.get("text_blocks", []),
                "has_chart": ocr_result.get("has_chart", False),
                "ocr_engine_used": "easyocr"
            }

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(result_data, f, ensure_ascii=False, indent=2)

            return {
                "success": True,
                "input_file": image_paths,
                "output_file": str(output_file),
                "ocr_result": result_data
            }
        else:
            # 如果是目录，调用 analyze_image_folder
            return extract_ocr_from_images(image_paths, file_type)
    else:
        # 处理多个图片
        return {
            "success": False,
            "error": "批量图片处理功能待实现"
        }


# 修改原有的测试主函数
if __name__ == "__main__":
    """
    测试EasyOCR提取
    """
    # 可配置的测试路径
    test_image_dir = r"D:\Python in school\try_project\smart_note\output\pdf\DM_20260415110819_001"  # 可以修改为其他路径


    # 添加文件类型推断函数
    def infer_file_type_from_path(image_dir: str) -> str:
        """从图片目录路径推断文件类型"""
        image_dir_lower = image_dir.lower()

        # 检查路径模式
        if r"output\pdf" in image_dir_lower or "output/pdf" in image_dir_lower:
            return "pdf"
        elif r"output\ppt" in image_dir_lower or "output/ppt" in image_dir_lower:
            return "ppt"

        # 检查路径关键词
        if "pdf" in image_dir_lower:
            return "pdf"
        elif "ppt" in image_dir_lower or "pptx" in image_dir_lower:
            return "ppt"

        return "pdf"  # 默认


    # 推断文件类型
    test_file_type = infer_file_type_from_path(test_image_dir)
    print(f"📁 推断文件类型: {test_file_type}")

    # 或者从命令行参数获取
    import sys

    if len(sys.argv) > 1:
        test_image_dir = sys.argv[1]
    if len(sys.argv) > 2:
        test_file_type = sys.argv[2]

    if not os.path.exists(test_image_dir):
        print(f"❌ 测试目录不存在: {test_image_dir}")
        print("请先运行ppt_img.py或pdf_img.py生成图片，或手动指定图片目录")
        print(f"示例: python ocr_extractor.py output/pdf/文件名")
        sys.exit(1)

    print("=" * 50)
    print("EasyOCR文本提取工具")
    print("=" * 50)

    result = process_ocr_for_alignment(test_image_dir, test_file_type)

    if result["success"]:
        print(f"\n📄 OCR结果摘要:")
        pages = result["ocr_results"]["pages"]
        print(f"  总页数: {len(pages)}")
        print(f"  使用引擎: {result['ocr_results']['ocr_engine_used']}")
        print(f"  输出文件: {result['output_file']}")

        # 显示前几页的摘要
        for i, page in enumerate(pages[:3]):
            if i < len(pages):
                ocr_text = page['ocr_text']
                preview = ocr_text[:100] + "..." if len(ocr_text) > 100 else ocr_text
                print(f"  第{page['page_number']}页:")
                print(f"    文字预览: {preview}")
                print(f"    OCR成功: {page.get('ocr_success', False)}")
                print()
    else:
        print(f"\n❌ OCR提取失败: {result.get('error', '未知错误')}")



