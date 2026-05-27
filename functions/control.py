"""
control.py
智能笔记系统调度控制器 - 线程安全修复版
"""

import os
import sys
import time
import json
import traceback
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import shutil
from config import Config
from database import SmartNoteDB, register_file_to_db


class SmartNoteScheduler:
    """
    智能笔记系统调度器
    统一协调所有处理模块的工作流程 - 线程安全版本
    """

    def __init__(self, debug_mode: bool = True):
        """
        初始化调度器
        注意：不在__init__中创建数据库连接，改为按需创建
        """
        self.debug_mode = debug_mode
        self.modules_available = {}
        self.db = None  # 延迟初始化

        # 导入各处理模块
        self._import_modules()

        if self.debug_mode:
            print("=" * 60)
            print("🤖 智能笔记系统调度器 - 启动")
            available = [k for k, v in self.modules_available.items() if v]
            print(f"📦 可用模块: {available}")
            print("=" * 60)

    def _get_db(self):
        """延迟获取数据库连接（线程安全）"""
        if self.db is None:
            try:
                self.db = SmartNoteDB()
                # 验证必要方法
                required_methods = [
                    'update_processing_status',
                    'update_conversion_result',
                    'update_ocr_result',
                    'update_transcription_result',
                    'update_alignment_result',
                    'update_note_result'
                ]
                for method in required_methods:
                    if not hasattr(self.db, method):
                        raise Exception(f"SmartNoteDB 缺少 {method} 方法")
            except Exception as e:
                print(f"❌ 数据库初始化失败: {e}")
                print("⚠️ 警告: 数据库功能不可用，将无法记录处理状态和结果")
                self.db = None
        return self.db

    def _import_modules(self):
        """导入所有处理模块，记录可用性"""
        modules_to_import = [
            ('pdf_img', 'convert_pdf_to_images', 'PDF转换'),
            ('ppt_img', 'convert_ppt_to_images', 'PPT转换'),
            ('sound', 'transcribe_audio', '音频转写'),
            ('ocr_extractor', 'extract_ocr_from_images', 'OCR提取'),
            ('aligner', 'align_audio_with_images', '内容对齐'),
            ('cre_note', 'generate_notes_for_web', '笔记生成')
        ]

        for module_name, func_name, display_name in modules_to_import:
            try:
                module = __import__(module_name, fromlist=[func_name])
                func = getattr(module, func_name)
                setattr(self, func_name, func)
                self.modules_available[display_name] = True
                if self.debug_mode:
                    print(f"✅ {display_name}模块加载成功")
            except ImportError as e:
                setattr(self, func_name, None)
                self.modules_available[display_name] = False
                if self.debug_mode:
                    print(f"⚠️ {display_name}模块不可用: {e}")

    def _get_file_type(self, file_path: str) -> str:
        """根据文件后缀判断文件类型"""
        if not os.path.exists(file_path):
            return "unknown"

        ext = Path(file_path).suffix.lower()

        if ext == '.pdf':
            return "pdf"
        elif ext in ['.ppt', '.pptx']:
            return "ppt"
        elif ext in ['.mp3', '.wav', '.m4a', '.flac', '.aac', '.ogg', '.opus']:
            return "audio"
        else:
            return "unknown"

    def _register_and_update_status(self, file_path: str, file_type: str) -> Optional[int]:
        """
        注册文件到数据库并更新状态
        使用独立的函数调用，确保线程安全
        """
        try:
            # 使用 register_file_to_db 函数（每次调用创建新连接）
            result = register_file_to_db(file_path, file_type)

            if not result["success"]:
                if self.debug_mode:
                    print(f"❌ 数据库注册失败: {result.get('error')}")
                return None

            source_id = result["source_id"]

            if self.debug_mode:
                print(f"✅ 文件已注册: ID={source_id}, 类型={file_type}")

            return source_id

        except Exception as e:
            if self.debug_mode:
                print(f"❌ 数据库注册操作失败: {e}")
                traceback.print_exc()
            return None

    def _update_db_status(self, source_id: int, stage: str, status: str, error_msg: str = None, stage_start_time: float = None) -> None:
        """
        统一更新处理状态的方法 - 使用独立连接
        """
        try:
            db = SmartNoteDB()  # 创建新的数据库实例（线程安全）
            db.update_processing_status(
                source_id=source_id,
                stage=stage,
                status=status,
                error=error_msg
            )
            db.close()
        except Exception as e:
            if self.debug_mode:
                print(f"⚠️ 更新数据库状态失败: {e}")

    def _record_db_result(self, result_type: str, **kwargs) -> None:
        """
        统一记录处理结果到数据库 - 使用独立连接
        """
        try:
            db = SmartNoteDB()  # 创建新的数据库实例（线程安全）
            method_map = {
                'conversion': db.update_conversion_result,
                'ocr': db.update_ocr_result,
                'transcription': db.update_transcription_result,
                'alignment': db.update_alignment_result,
                'note': db.update_note_result
            }

            if result_type in method_map:
                method_map[result_type](**kwargs)
            db.close()
        except Exception as e:
            if self.debug_mode:
                print(f"⚠️ 记录数据库结果失败: {e}")

    def process_document(self, doc_path: str, audio_path: str = None,
                         source_name: str = None, file_type: str = "auto") -> Dict:
        """
        处理文档文件（PDF/PPT）完整流程
        """
        if self.debug_mode:
            print("" + "=" * 60)
            print("📄 开始处理文档")
            print("=" * 60)

        # 1. 验证文件存在
        if not os.path.exists(doc_path):
            return {"success": False, "error": f"文档文件不存在: {doc_path}"}

        # 2. 自动检测文件类型
        if file_type == "auto":
            file_type = self._get_file_type(doc_path)

        if file_type not in ["pdf", "ppt"]:
            return {"success": False, "error": f"不支持的文件类型: {file_type}"}

        # 3. 提取源文件名
        if source_name is None:
            source_name = Path(doc_path).stem

        if self.debug_mode:
            print(f"📁 文档信息:")
            print(f"  - 文件: {Path(doc_path).name}")
            print(f"  - 类型: {file_type}")
            print(f"  - 源名: {source_name}")

        # 4. 注册文档到数据库
        doc_source_id = self._register_and_update_status(doc_path, file_type)
        if not doc_source_id:
            return {"success": False, "error": "数据库注册失败"}

        result_pipeline = {
            "success": False,
            "source_name": source_name,
            "file_type": file_type,
            "document_source_id": doc_source_id,
            "audio_source_id": None,
            "stages": {}
        }

        # 5. 转换文档为图片
        if self.debug_mode:
            print(f"🔄 阶段1: 转换文档为图片")

        stage_start_time = time.time()
        conversion_id = None
        try:
            if file_type == "pdf":
                if not self.convert_pdf_to_images:
                    return {"success": False, "error": "PDF转换模块不可用"}
                conversion_result = self.convert_pdf_to_images(doc_path, output_base_dir=None)
            elif file_type == "ppt":
                if not self.convert_ppt_to_images:
                    return {"success": False, "error": "PPT转换模块不可用"}
                conversion_result = self.convert_ppt_to_images(doc_path, output_base_dir=None)
            else:
                return {"success": False, "error": f"不支持的文件类型: {file_type}"}

            if not conversion_result.get("success"):
                error_msg = conversion_result.get("error", "未知转换错误")
                self._update_db_status(doc_source_id, "conversion", "failed", error_msg, stage_start_time)
                return {"success": False, "error": f"文档转换失败: {error_msg}"}

            # 记录转换结果和状态（使用独立连接）
            try:
                db = SmartNoteDB()
                conversion_id = db.update_conversion_result(
                    source_id=doc_source_id,
                    output_dir=conversion_result["output_dir"],
                    image_count=conversion_result["image_count"],
                    status="success"
                )
                db.update_processing_status(doc_source_id, "conversion", "completed")
                db.close()
            except Exception as db_err:
                print(f"⚠️ 记录转换结果到数据库失败: {db_err}")
                conversion_id = None

            result_pipeline["stages"]["conversion"] = {
                "success": True,
                "output_dir": conversion_result["output_dir"],
                "image_count": conversion_result["image_count"],
                "conversion_id": conversion_id
            }

            if self.debug_mode:
                print(f"✅ 转换完成: {conversion_result['image_count']} 张图片")
                print(f"✅ 转换记录ID: {conversion_id}")

        except Exception as e:
            error_msg = f"文档转换异常: {str(e)}"
            self._update_db_status(doc_source_id, "conversion", "failed", str(e), stage_start_time)
            return {"success": False, "error": error_msg}

        # 6. OCR提取文字
        if self.debug_mode:
            print(f"🔍 阶段2: OCR文字提取")

        stage_start_time = time.time()
        ocr_id = None
        try:
            if not self.extract_ocr_from_images:
                return {"success": False, "error": "OCR模块不可用"}

            image_dir = conversion_result["output_dir"]
            ocr_result = self.extract_ocr_from_images(image_dir, file_type)

            if not ocr_result.get("success"):
                error_msg = ocr_result.get("error", "未知OCR错误")
                self._update_db_status(doc_source_id, "ocr", "failed", error_msg, stage_start_time)
                return {"success": False, "error": f"OCR提取失败: {error_msg}"}

            # 记录OCR结果（使用独立连接）
            try:
                ocr_output_file = ocr_result.get("output_file")
                if ocr_output_file and os.path.exists(ocr_output_file):
                    with open(ocr_output_file, 'r', encoding='utf-8') as f:
                        ocr_content = f.read()
                else:
                    ocr_content = ""

                page_count = ocr_result.get("ocr_results", {}).get("total_pages", 0)
                chart_pages = ocr_result.get("ocr_results", {}).get("chart_pages", 0)
                text_length = len(ocr_content)

                db = SmartNoteDB()
                ocr_id = db.update_ocr_result(
                    conversion_id=conversion_id,
                    ocr_file_path=ocr_output_file,
                    page_count=page_count,
                    text_length=text_length,
                    chart_pages=chart_pages
                )
                db.update_processing_status(doc_source_id, "ocr", "completed")
                db.close()
            except Exception as db_err:
                print(f"⚠️ 记录OCR结果到数据库失败: {db_err}")
                ocr_id = None

            result_pipeline["stages"]["ocr"] = {
                "success": True,
                "ocr_file": ocr_output_file,
                "page_count": page_count,
                "ocr_id": ocr_id
            }

            if self.debug_mode:
                print(f"✅ OCR提取完成: {page_count} 页")
                print(f"✅ OCR记录ID: {ocr_id}")

        except Exception as e:
            error_msg = f"OCR提取异常: {str(e)}"
            self._update_db_status(doc_source_id, "ocr", "failed", str(e), stage_start_time)
            return {"success": False, "error": error_msg}

        # 如果没有音频文件，直接结束
        if not audio_path or not os.path.exists(audio_path):
            if self.debug_mode:
                print(f"⚠️ 没有音频文件，流程结束")

            result_pipeline["success"] = True
            result_pipeline["has_audio"] = False
            result_pipeline["notes_output"] = {
                "markdown": ocr_result.get("output_file"),
                "mindmap": None
            }
            return result_pipeline

        # 7. 处理音频文件
        if self.debug_mode:
            print(f"🎵 阶段3: 音频转写处理")

        audio_source_id = None
        transcription_id = None
        stage_start_time = time.time()
        try:
            audio_source_id = self._register_and_update_status(audio_path, "audio")
            if not audio_source_id:
                return {"success": False, "error": "音频数据库注册失败"}

            result_pipeline["audio_source_id"] = audio_source_id

            if not self.transcribe_audio:
                return {"success": False, "error": "音频转写模块不可用"}

            transcription_result = self.transcribe_audio(
                audio_path,
                output_base_dir=None,
                model_size="medium",
                language=None
            )

            if not transcription_result.get("success"):
                error_msg = transcription_result.get("error", "未知转写错误")
                self._update_db_status(audio_source_id, "transcription", "failed", error_msg, stage_start_time)
                return {"success": False, "error": f"音频转写失败: {error_msg}"}

            # 记录转写结果（使用独立连接）
            try:
                transcription_file = transcription_result.get("output_file")
                full_text = transcription_result.get("full_text", "")
                segment_count = transcription_result.get("segment_count", 0)
                language = transcription_result.get("language", "unknown")
                model_used = transcription_result.get("model", "whisper")

                db = SmartNoteDB()
                transcription_id = db.update_transcription_result(
                    source_id=audio_source_id,
                    transcription_file=transcription_file,
                    model_used=model_used,
                    language=language,
                    segment_count=segment_count,
                    text_length=len(full_text)
                )
                db.update_processing_status(audio_source_id, "transcription", "completed")
                db.close()
            except Exception as db_err:
                print(f"⚠️ 记录转写结果到数据库失败: {db_err}")
                transcription_id = None

            result_pipeline["stages"]["transcription"] = {
                "success": True,
                "transcription_file": transcription_file,
                "segment_count": segment_count,
                "language": language,
                "transcription_id": transcription_id
            }

            if self.debug_mode:
                print(f"✅ 音频转写完成: {segment_count} 段")
                print(f"✅ 转写记录ID: {transcription_id}")

        except Exception as e:
            error_msg = f"音频处理异常: {str(e)}"
            if audio_source_id:
                self._update_db_status(audio_source_id, "transcription", "failed", str(e), stage_start_time)
            return {"success": False, "error": error_msg}

        # 8. 对齐处理
        if self.debug_mode:
            print(f"🔗 阶段4: 音频与文档对齐")

        stage_start_time = time.time()
        alignment_id = None
        try:
            if not self.align_audio_with_images:
                return {"success": False, "error": "对齐模块不可用"}

            alignment_result = self.align_audio_with_images(
                image_dir=conversion_result["output_dir"],
                transcription_json=transcription_result["output_file"],
                file_type=file_type
            )

            if not alignment_result.get("success"):
                error_msg = alignment_result.get("error", "未知对齐错误")
                self._update_db_status(doc_source_id, "alignment", "failed", error_msg, stage_start_time)
                return {"success": False, "error": f"对齐失败: {error_msg}"}

            # 获取对齐统计信息
            alignment_data = alignment_result.get("alignment_data", {})
            total_pages = alignment_data.get("total_pages", 0)
            total_audio_segments = alignment_data.get("total_audio_segments", 0)
            matched_pages = alignment_data.get("matched_pages", 0)
            audio_only_segments = alignment_data.get("audio_only_segments", 0)
            alignment_file = alignment_result.get("output_file")

            # 记录对齐结果（使用独立连接）
            try:
                db = SmartNoteDB()
                alignment_id = db.update_alignment_result(
                    ocr_id=ocr_id,
                    transcription_id=transcription_id,
                    alignment_file=alignment_file,
                    file_type=file_type,
                    source_name=source_name,
                    total_pages=total_pages,
                    total_audio_segments=total_audio_segments,
                    matched_pages=matched_pages,
                    audio_only_segments=audio_only_segments
                )
                db.update_processing_status(doc_source_id, "alignment", "completed")
                db.close()
            except Exception as db_err:
                print(f"⚠️ 记录对齐结果到数据库失败: {db_err}")
                alignment_id = None

            result_pipeline["stages"]["alignment"] = {
                "success": True,
                "alignment_file": alignment_file,
                "matched_pages": matched_pages,
                "alignment_id": alignment_id
            }

            if self.debug_mode:
                print(f"✅ 对齐完成: {matched_pages} 页匹配")
                print(f"✅ 对齐记录ID: {alignment_id}")

        except Exception as e:
            error_msg = f"对齐处理异常: {str(e)}"
            self._update_db_status(doc_source_id, "alignment", "failed", str(e), stage_start_time)
            return {"success": False, "error": error_msg}

        # 9. 笔记生成
        if self.debug_mode:
            print(f"📒 阶段5: 智能笔记生成")

        stage_start_time = time.time()
        try:
            if not self.generate_notes_for_web:
                return {"success": False, "error": "笔记生成模块不可用"}

            notes_result = self.generate_notes_for_web(
                alignment_json_path=alignment_result["output_file"],
                source_name=source_name,
                file_type=file_type
            )

            if not notes_result.get("success"):
                error_msg = notes_result.get("error", "未知笔记生成错误")
                self._update_db_status(doc_source_id, "notes", "failed", error_msg, stage_start_time)
                return {"success": False, "error": f"笔记生成失败: {error_msg}"}

            # 记录笔记结果（使用独立连接）
            try:
                notes_path = notes_result.get("notes_path")
                mindmap_path = notes_result.get("mindmap_path")

                if notes_path and os.path.exists(notes_path):
                    with open(notes_path, 'r', encoding='utf-8') as f:
                        markdown_content = f.read()
                else:
                    markdown_content = ""

                db = SmartNoteDB()
                note_id = db.update_note_result(
                    alignment_id=alignment_id,
                    markdown_file=notes_path,
                    mindmap_file=mindmap_path,
                    note_style="academic",
                    markdown_length=len(markdown_content)
                )
                db.update_processing_status(doc_source_id, "notes", "completed")
                db.close()
            except Exception as db_err:
                print(f"⚠️ 记录笔记结果到数据库失败: {db_err}")
                note_id = None

            result_pipeline["stages"]["notes"] = {
                "success": True,
                "notes_file": notes_path,
                "mindmap_file": mindmap_path,
                "markdown_length": len(markdown_content) if markdown_content else 0,
                "note_id": note_id
            }

            if self.debug_mode:
                print(f"✅ 笔记生成完成")
                print(f"   笔记文件: {notes_path}")
                if mindmap_path:
                    print(f"   思维导图: {mindmap_path}")
                print(f"   笔记记录ID: {note_id}")

        except Exception as e:
            error_msg = f"笔记生成异常: {str(e)}"
            self._update_db_status(doc_source_id, "notes", "failed", str(e), stage_start_time)
            return {"success": False, "error": error_msg}

        # 设置最终结果
        result_pipeline["success"] = True
        result_pipeline["has_audio"] = True
        result_pipeline["notes_output"] = {
            "markdown": notes_result.get("notes_path"),
            "mindmap": notes_result.get("mindmap_path")
        }

        if self.debug_mode:
            print(f"" + "=" * 60)
            print(f"🎉 所有处理完成!")
            print("=" * 60)
            print(f"📁 最终输出:")
            print(f"  - 笔记文件: {notes_result.get('notes_path')}")
            print(f"  - 思维导图: {mindmap_path}")
            print(f"  - 源文件ID: {doc_source_id}")
            print(f"  - 最终笔记ID: {note_id}")

        return result_pipeline

    def process_audio_only(self, audio_path: str, source_name: str = None) -> Dict:
        """处理纯音频文件（无文档）"""
        if self.debug_mode:
            print("" + "=" * 60)
            print("🎵 开始处理纯音频文件")
            print("=" * 60)

        if not os.path.exists(audio_path):
            return {"success": False, "error": f"音频文件不存在: {audio_path}"}

        if source_name is None:
            source_name = Path(audio_path).stem

        if self.debug_mode:
            print(f"📁 音频信息:")
            print(f"  - 文件: {Path(audio_path).name}")
            print(f"  - 源名: {source_name}")

        audio_source_id = self._register_and_update_status(audio_path, "audio")
        if not audio_source_id:
            return {"success": False, "error": "数据库注册失败"}

        result = {
            "success": False,
            "source_name": source_name,
            "file_type": "audio",
            "audio_source_id": audio_source_id,
            "stages": {}
        }

        if self.debug_mode:
            print(f"🔄 阶段1: 音频转写")

        stage_start_time = time.time()
        try:
            if not self.transcribe_audio:
                return {"success": False, "error": "音频转写模块不可用"}

            transcription_result = self.transcribe_audio(
                audio_path,
                output_base_dir=None,
                model_size="medium",
                language=None
            )

            if not transcription_result.get("success"):
                error_msg = transcription_result.get("error", "未知转写错误")
                self._update_db_status(audio_source_id, "transcription", "failed", error_msg, stage_start_time)
                return {"success": False, "error": f"音频转写失败: {error_msg}"}

            # 记录转写结果（使用独立连接）
            try:
                transcription_file = transcription_result.get("output_file")
                full_text = transcription_result.get("full_text", "")
                segment_count = transcription_result.get("segment_count", 0)
                language = transcription_result.get("language", "unknown")
                model_used = transcription_result.get("model", "whisper")

                db = SmartNoteDB()
                transcription_id = db.update_transcription_result(
                    source_id=audio_source_id,
                    transcription_file=transcription_file,
                    model_used=model_used,
                    language=language,
                    segment_count=segment_count,
                    text_length=len(full_text)
                )
                db.update_processing_status(audio_source_id, "transcription", "completed")
                db.close()
            except Exception as db_err:
                print(f"⚠️ 记录转写结果到数据库失败: {db_err}")
                transcription_id = None

            result["stages"]["transcription"] = {
                "success": True,
                "transcription_file": transcription_file,
                "segment_count": segment_count,
                "language": language,
                "transcription_id": transcription_id
            }

            if self.debug_mode:
                print(f"✅ 音频转写完成: {segment_count} 段")
                print(f"✅ 转写记录ID: {transcription_id}")

        except Exception as e:
            error_msg = f"音频转写异常: {str(e)}"
            self._update_db_status(audio_source_id, "transcription", "failed", str(e), stage_start_time)
            return {"success": False, "error": error_msg}

        if self.debug_mode:
            print(f"✅ 纯音频处理完成!")
            print(f"📁 输出文件: {result['stages']['transcription']['transcription_file']}")

        result["success"] = True
        return result

    def close(self):
        """关闭调度器"""
        if self.db:
            try:
                self.db.close()
            except:
                pass
            self.db = None

        if self.debug_mode:
            print("🔄 调度器已关闭")


# ========== 命令行接口 ==========

def process_pipeline():
    """命令行调度接口"""
    import sys

    if len(sys.argv) < 2:
        print("📋 智能笔记系统调度器 - 用法:")
        print("  1. 处理文档+音频: python scheduler.py <文档路径> [音频路径]")
        print("  2. 处理纯音频: python scheduler.py --audio-only <音频路径>")
        print("  3. 测试模式: python scheduler.py test")
        return

    scheduler = SmartNoteScheduler(debug_mode=True)

    try:
        if sys.argv[1] == "test":
            print("🧪 测试模式")
            import tempfile

            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                f.write("Test document content")
                test_doc = f.name

            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                f.write("Test audio content")
                test_audio = f.name

            try:
                print("📄 测试文档处理...")
                result = scheduler.process_document(test_doc, test_audio, "test_file")
                print(f"结果: {'成功' if result.get('success') else '失败'}")

                if result.get("success"):
                    print(f"输出: {result.get('notes_output', {})}")

                os.unlink(test_doc)
                os.unlink(test_audio)

            except Exception as e:
                print(f"❌ 测试失败: {e}")

        elif sys.argv[1] == "--audio-only" and len(sys.argv) > 2:
            audio_path = sys.argv[2]
            result = scheduler.process_audio_only(audio_path)
            print(json.dumps(result, ensure_ascii=False, indent=2))

        elif len(sys.argv) >= 2:
            doc_path = sys.argv[1]
            audio_path = sys.argv[2] if len(sys.argv) > 2 else None

            result = scheduler.process_document(doc_path, audio_path)
            print(json.dumps(result, ensure_ascii=False, indent=2))

    except Exception as e:
        print(f"❌ 调度失败: {e}")
        traceback.print_exc()

    finally:
        scheduler.close()


if __name__ == "__main__":
    process_pipeline()