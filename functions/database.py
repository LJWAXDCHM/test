"""
db_manager.py
智能笔记系统数据库管理模块 - 线程安全修复版
"""

import os
import json
import sqlite3
import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from config import Config
import hashlib
import threading


class SmartNoteDB:
    """
    智能笔记系统数据库管理器 - 线程安全版本
    每个线程拥有独立的数据库连接
    """

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_dir = Config.get_output_path("database")
            db_path = os.path.join(db_dir, "smart_note.db")

        self.db_path = db_path
        # 使用线程本地存储，每个线程独立连接
        self._local = threading.local()
        self._init_database()
        print(f"✅ 数据库初始化完成: {self.db_path}")

    @property
    def conn(self):
        """获取当前线程的数据库连接"""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            self._local.connection = sqlite3.connect(self.db_path, check_same_thread=False)
            # 启用WAL模式，提高并发性能
            self._local.connection.execute("PRAGMA journal_mode=WAL")
            self._local.connection.execute("PRAGMA synchronous=NORMAL")
            self._local.connection.execute("PRAGMA busy_timeout=5000")
        return self._local.connection

    def _init_database(self):
        """初始化数据库表结构 - 使用临时连接"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 1. 源文件表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS source_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            file_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER,
            md5_hash TEXT UNIQUE,
            upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'pending'
        )
        """)

        # 2. PDF/PPT转换结果表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS pdf_ppt_conversions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER,
            output_dir TEXT NOT NULL,
            image_count INTEGER,
            conversion_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'success',
            error_message TEXT,
            FOREIGN KEY (source_id) REFERENCES source_files (id)
        )
        """)

        # 3. OCR结果表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS ocr_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversion_id INTEGER,
            ocr_file_path TEXT NOT NULL,
            page_count INTEGER,
            text_length INTEGER,
            chart_pages INTEGER,
            ocr_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ocr_engine TEXT DEFAULT 'easyocr',
            FOREIGN KEY (conversion_id) REFERENCES pdf_ppt_conversions (id)
        )
        """)

        # 4. 音频转写结果表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS audio_transcriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER,
            transcription_file TEXT NOT NULL,
            model_used TEXT,
            language TEXT,
            segment_count INTEGER,
            text_length INTEGER,
            transcription_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (source_id) REFERENCES source_files (id)
        )
        """)

        # 5. 对齐结果表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS alignment_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ocr_id INTEGER,
            transcription_id INTEGER,
            alignment_file TEXT NOT NULL,
            file_type TEXT,
            source_name TEXT,
            total_pages INTEGER,
            total_audio_segments INTEGER,
            matched_pages INTEGER,
            audio_only_segments INTEGER,
            alignment_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (ocr_id) REFERENCES ocr_results (id),
            FOREIGN KEY (transcription_id) REFERENCES audio_transcriptions (id)
        )
        """)

        # 6. 笔记生成结果表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS note_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alignment_id INTEGER,
            markdown_file TEXT NOT NULL,
            mindmap_file TEXT,
            note_style TEXT DEFAULT 'academic',
            markdown_length INTEGER,
            generation_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            model_used TEXT DEFAULT 'glm-4-flash-250414',
            FOREIGN KEY (alignment_id) REFERENCES alignment_results (id)
        )
        """)

        # 7. 处理状态表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS processing_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER,
            stage TEXT NOT NULL,
            status TEXT NOT NULL,
            start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            end_time TIMESTAMP,
            error_message TEXT,
            FOREIGN KEY (source_id) REFERENCES source_files (id)
        )
        """)

        # 创建索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_source_files_md5 ON source_files(md5_hash)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_status_stage ON processing_status(stage, status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_source_files_type ON source_files(file_type, status)')

        conn.commit()
        conn.close()
        print(f"✅ 数据库表结构初始化完成")

    def _get_file_md5(self, file_path: str) -> str:
        """计算文件的MD5哈希值"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def register_source_file(self, file_path: str, file_type: str) -> int:
        """注册源文件到数据库"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        md5_hash = self._get_file_md5(file_path)

        cursor = self.conn.cursor()

        # 检查是否已存在
        cursor.execute('SELECT id FROM source_files WHERE md5_hash = ?', (md5_hash,))
        existing = cursor.fetchone()

        if existing:
            print(f"⚠️ 文件已存在，ID: {existing[0]}")
            return existing[0]

        # 插入新记录
        cursor.execute("""
        INSERT INTO source_files (filename, file_type, file_path, file_size, md5_hash, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
        """, (filename, file_type, file_path, file_size, md5_hash))

        source_id = cursor.lastrowid

        # 初始化处理状态
        stages = ['conversion', 'ocr', 'transcription', 'alignment', 'notes']
        for stage in stages:
            cursor.execute("""
            INSERT INTO processing_status (source_id, stage, status)
            VALUES (?, ?, 'pending')
            """, (source_id, stage))

        self.conn.commit()
        print(f"✅ 注册源文件: {filename} (ID: {source_id})")
        return source_id

    def update_conversion_result(self, source_id: int, output_dir: str, image_count: int,
                                 status: str = 'success', error: str = None) -> int:
        """更新PDF/PPT转换结果"""
        cursor = self.conn.cursor()

        cursor.execute("""
        INSERT INTO pdf_ppt_conversions (source_id, output_dir, image_count, status, error_message)
        VALUES (?, ?, ?, ?, ?)
        """, (source_id, output_dir, image_count, status, error))

        conversion_id = cursor.lastrowid

        # 更新处理状态
        cursor.execute("""
        UPDATE processing_status 
        SET status = ?, end_time = CURRENT_TIMESTAMP, error_message = ?
        WHERE source_id = ? AND stage = 'conversion'
        """, (status, error, source_id))

        # 更新源文件状态
        if status == 'success':
            cursor.execute("""
            UPDATE source_files SET status = 'processing' WHERE id = ?
            """, (source_id,))

        self.conn.commit()
        print(f"✅ 记录转换结果: ID={conversion_id}, 图片数={image_count}")
        return conversion_id

    def update_ocr_result(self, conversion_id: int, ocr_file_path: str, page_count: int,
                          text_length: int, chart_pages: int = 0) -> int:
        """更新OCR结果"""
        cursor = self.conn.cursor()

        # 获取源文件ID
        cursor.execute('SELECT source_id FROM pdf_ppt_conversions WHERE id = ?', (conversion_id,))
        source_result = cursor.fetchone()

        if not source_result:
            raise ValueError(f"转换记录不存在: {conversion_id}")

        source_id = source_result[0]

        cursor.execute("""
        INSERT INTO ocr_results (conversion_id, ocr_file_path, page_count, text_length, chart_pages)
        VALUES (?, ?, ?, ?, ?)
        """, (conversion_id, ocr_file_path, page_count, text_length, chart_pages))

        ocr_id = cursor.lastrowid

        # 更新处理状态
        cursor.execute("""
        UPDATE processing_status 
        SET status = 'completed', end_time = CURRENT_TIMESTAMP
        WHERE source_id = ? AND stage = 'ocr'
        """, (source_id,))

        self.conn.commit()
        print(f"✅ 记录OCR结果: ID={ocr_id}, 页数={page_count}")
        return ocr_id

    def update_transcription_result(self, source_id: int, transcription_file: str,
                                    model_used: str, language: str, segment_count: int,
                                    text_length: int) -> int:
        """更新音频转写结果"""
        cursor = self.conn.cursor()

        cursor.execute("""
        INSERT INTO audio_transcriptions 
        (source_id, transcription_file, model_used, language, segment_count, text_length)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (source_id, transcription_file, model_used, language, segment_count, text_length))

        transcription_id = cursor.lastrowid

        # 更新处理状态
        cursor.execute("""
        UPDATE processing_status 
        SET status = 'completed', end_time = CURRENT_TIMESTAMP
        WHERE source_id = ? AND stage = 'transcription'
        """, (source_id,))

        self.conn.commit()
        print(f"✅ 记录音频转写结果: ID={transcription_id}, 分段={segment_count}")
        return transcription_id

    def update_alignment_result(self, ocr_id: int, transcription_id: int, alignment_file: str,
                                file_type: str, source_name: str, total_pages: int,
                                total_audio_segments: int, matched_pages: int,
                                audio_only_segments: int) -> int:
        """更新对齐结果"""
        cursor = self.conn.cursor()

        # 获取源文件ID
        cursor.execute("""
        SELECT pc.source_id 
        FROM ocr_results ocr
        JOIN pdf_ppt_conversions pc ON ocr.conversion_id = pc.id
        WHERE ocr.id = ?
        """, (ocr_id,))
        source_result = cursor.fetchone()

        if not source_result:
            raise ValueError(f"相关记录不存在")

        source_id = source_result[0]

        cursor.execute("""
        INSERT INTO alignment_results 
        (ocr_id, transcription_id, alignment_file, file_type, source_name, 
         total_pages, total_audio_segments, matched_pages, audio_only_segments)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ocr_id, transcription_id, alignment_file, file_type, source_name,
              total_pages, total_audio_segments, matched_pages, audio_only_segments))

        alignment_id = cursor.lastrowid

        # 更新处理状态
        cursor.execute("""
        UPDATE processing_status 
        SET status = 'completed', end_time = CURRENT_TIMESTAMP
        WHERE source_id = ? AND stage = 'alignment'
        """, (source_id,))

        self.conn.commit()
        print(f"✅ 记录对齐结果: ID={alignment_id}, 匹配页={matched_pages}")
        return alignment_id

    def update_note_result(self, alignment_id: int, markdown_file: str, mindmap_file: str = None,
                           note_style: str = 'academic', markdown_length: int = 0) -> int:
        """更新笔记生成结果"""
        cursor = self.conn.cursor()

        # 获取源文件ID
        cursor.execute("""
        SELECT pc.source_id 
        FROM alignment_results ar
        JOIN ocr_results ocr ON ar.ocr_id = ocr.id
        JOIN pdf_ppt_conversions pc ON ocr.conversion_id = pc.id
        WHERE ar.id = ?
        """, (alignment_id,))
        source_result = cursor.fetchone()

        if not source_result:
            raise ValueError(f"对齐记录不存在: {alignment_id}")

        source_id = source_result[0]

        cursor.execute("""
        INSERT INTO note_results 
        (alignment_id, markdown_file, mindmap_file, note_style, markdown_length, model_used)
        VALUES (?, ?, ?, ?, ?, 'glm-4-flash-250414')
        """, (alignment_id, markdown_file, mindmap_file, note_style, markdown_length))

        note_id = cursor.lastrowid

        # 更新处理状态
        cursor.execute("""
        UPDATE processing_status 
        SET status = 'completed', end_time = CURRENT_TIMESTAMP
        WHERE source_id = ? AND stage = 'notes'
        """, (source_id,))

        # 更新源文件状态为完成
        cursor.execute("""
        UPDATE source_files SET status = 'completed' WHERE id = ?
        """, (source_id,))

        self.conn.commit()
        print(f"✅ 记录笔记结果: ID={note_id}, 文件={markdown_file}")
        return note_id

    def update_processing_status(self, source_id: int, stage: str, status: str, error: str = None):
        """更新处理状态"""
        cursor = self.conn.cursor()

        cursor.execute("""
        UPDATE processing_status 
        SET status = ?, end_time = CURRENT_TIMESTAMP, error_message = ?
        WHERE source_id = ? AND stage = ?
        """, (status, error, source_id, stage))

        if status == 'failed':
            cursor.execute("""
            UPDATE source_files SET status = 'failed' WHERE id = ?
            """, (source_id,))

        self.conn.commit()
        print(f"📊 更新状态: source={source_id}, stage={stage}, status={status}")

    def get_source_info(self, source_id: int) -> Dict:
        """获取源文件信息"""
        cursor = self.conn.cursor()
        cursor.execute("""
        SELECT id, filename, file_type, file_path, file_size, upload_time, status
        FROM source_files WHERE id = ?
        """, (source_id,))

        row = cursor.fetchone()
        if not row:
            return None

        return {
            'id': row[0],
            'filename': row[1],
            'file_type': row[2],
            'file_path': row[3],
            'file_size': row[4],
            'upload_time': row[5],
            'status': row[6]
        }

    def get_processing_status(self, source_id: int) -> Dict:
        """获取处理状态"""
        cursor = self.conn.cursor()
        cursor.execute("""
        SELECT stage, status, start_time, end_time, error_message
        FROM processing_status WHERE source_id = ? ORDER BY start_time
        """, (source_id,))

        status = {}
        for row in cursor.fetchall():
            status[row[0]] = {
                'status': row[1],
                'start_time': row[2],
                'end_time': row[3],
                'error_message': row[4]
            }

        return status

    def get_full_pipeline_result(self, source_id: int) -> Dict:
        """获取完整流水线结果"""
        cursor = self.conn.cursor()

        # 获取源文件信息
        source_info = self.get_source_info(source_id)
        if not source_info:
            return None

        result = {'source': source_info}

        # 获取转换结果
        cursor.execute("""
        SELECT id, output_dir, image_count, conversion_time, status, error_message
        FROM pdf_ppt_conversions WHERE source_id = ? ORDER BY id DESC LIMIT 1
        """, (source_id,))
        conversion_row = cursor.fetchone()

        if conversion_row:
            conversion_id = conversion_row[0]
            result['conversion'] = {
                'id': conversion_row[0],
                'output_dir': conversion_row[1],
                'image_count': conversion_row[2],
                'time': conversion_row[3],
                'status': conversion_row[4],
                'error': conversion_row[5]
            }

            # 获取OCR结果
            cursor.execute("""
            SELECT id, ocr_file_path, page_count, text_length, chart_pages, ocr_time
            FROM ocr_results WHERE conversion_id = ? ORDER BY id DESC LIMIT 1
            """, (conversion_id,))
            ocr_row = cursor.fetchone()

            if ocr_row:
                ocr_id = ocr_row[0]
                result['ocr'] = {
                    'id': ocr_row[0],
                    'ocr_file': ocr_row[1],
                    'page_count': ocr_row[2],
                    'text_length': ocr_row[3],
                    'chart_pages': ocr_row[4],
                    'time': ocr_row[5]
                }

        # 获取音频转写结果
        cursor.execute("""
        SELECT id, transcription_file, model_used, language, segment_count, text_length, transcription_time
        FROM audio_transcriptions WHERE source_id = ? ORDER BY id DESC LIMIT 1
        """, (source_id,))
        transcription_row = cursor.fetchone()

        if transcription_row:
            transcription_id = transcription_row[0]
            result['transcription'] = {
                'id': transcription_row[0],
                'transcription_file': transcription_row[1],
                'model_used': transcription_row[2],
                'language': transcription_row[3],
                'segment_count': transcription_row[4],
                'text_length': transcription_row[5],
                'time': transcription_row[6]
            }

        # 获取对齐结果
        if 'ocr' in result and 'transcription' in result:
            cursor.execute("""
            SELECT id, alignment_file, file_type, source_name, total_pages, 
                   total_audio_segments, matched_pages, audio_only_segments, alignment_time
            FROM alignment_results 
            WHERE ocr_id = ? AND transcription_id = ? 
            ORDER BY id DESC LIMIT 1
            """, (ocr_id, transcription_id))

            alignment_row = cursor.fetchone()
            if alignment_row:
                alignment_id = alignment_row[0]
                result['alignment'] = {
                    'id': alignment_row[0],
                    'alignment_file': alignment_row[1],
                    'file_type': alignment_row[2],
                    'source_name': alignment_row[3],
                    'total_pages': alignment_row[4],
                    'total_audio_segments': alignment_row[5],
                    'matched_pages': alignment_row[6],
                    'audio_only_segments': alignment_row[7],
                    'time': alignment_row[8]
                }

                # 获取笔记结果
                cursor.execute("""
                SELECT id, markdown_file, mindmap_file, note_style, markdown_length, generation_time
                FROM note_results WHERE alignment_id = ? ORDER BY id DESC LIMIT 1
                """, (alignment_id,))

                note_row = cursor.fetchone()
                if note_row:
                    result['notes'] = {
                        'id': note_row[0],
                        'markdown_file': note_row[1],
                        'mindmap_file': note_row[2],
                        'note_style': note_row[3],
                        'markdown_length': note_row[4],
                        'time': note_row[5]
                    }

        # 获取处理状态
        result['processing_status'] = self.get_processing_status(source_id)

        return result

    def search_files(self, filename: str = None, file_type: str = None,
                     status: str = None, limit: int = 50) -> List[Dict]:
        """搜索文件"""
        cursor = self.conn.cursor()

        query = "SELECT id, filename, file_type, file_path, upload_time, status FROM source_files WHERE 1=1"
        params = []

        if filename:
            query += " AND filename LIKE ?"
            params.append(f"%{filename}%")

        if file_type:
            query += " AND file_type = ?"
            params.append(file_type)

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY upload_time DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)

        results = []
        for row in cursor.fetchall():
            results.append({
                'id': row[0],
                'filename': row[1],
                'file_type': row[2],
                'file_path': row[3],
                'upload_time': row[4],
                'status': row[5]
            })

        return results

    def close(self):
        """关闭当前线程的数据库连接"""
        if hasattr(self._local, 'connection') and self._local.connection:
            self._local.connection.close()
            self._local.connection = None
            print("✅ 数据库连接已关闭")


# ========== 网页接口函数 ==========

def register_file_to_db(file_path: str, file_type: str, db_path: str = None) -> Dict:
    """
    网页接口：注册文件到数据库
    每次调用创建独立的数据库实例（线程安全）
    """
    try:
        db = SmartNoteDB(db_path)
        source_id = db.register_source_file(file_path, file_type)
        db.close()

        return {
            "success": True,
            "source_id": source_id,
            "message": f"文件已注册，ID: {source_id}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def get_file_status(source_id: int, db_path: str = None) -> Dict:
    """网页接口：获取文件处理状态"""
    try:
        db = SmartNoteDB(db_path)

        # 获取源文件信息
        source_info = db.get_source_info(source_id)
        if not source_info:
            return {"success": False, "error": f"文件不存在: {source_id}"}

        # 获取处理状态
        status = db.get_processing_status(source_id)

        # 获取完整结果
        pipeline_result = db.get_full_pipeline_result(source_id)

        db.close()

        return {
            "success": True,
            "source_info": source_info,
            "processing_status": status,
            "pipeline_result": pipeline_result
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def search_files_in_db(filename: str = None, file_type: str = None,
                       status: str = None, limit: int = 50, db_path: str = None) -> Dict:
    """网页接口：搜索文件"""
    try:
        db = SmartNoteDB(db_path)
        results = db.search_files(filename, file_type, status, limit)
        db.close()

        return {
            "success": True,
            "count": len(results),
            "results": results
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


# ========== 测试函数 ==========

def test_database():
    """测试数据库功能"""
    print("=" * 50)
    print("🧪 测试数据库模块")
    print("=" * 50)

    import sys
    import tempfile

    # 测试数据库路径
    test_db_path = None

    if len(sys.argv) > 1:
        test_db_path = sys.argv[1]
        print(f"📁 使用指定数据库: {test_db_path}")

    # 创建测试文件
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("Test content")
        test_file = f.name

    try:
        # 1. 初始化数据库
        db = SmartNoteDB(test_db_path)

        # 2. 注册测试文件
        source_id = db.register_source_file(test_file, "txt")
        print(f"✅ 注册文件成功，ID: {source_id}")

        # 3. 模拟转换结果
        conv_id = db.update_conversion_result(source_id, "/test/output", 5)
        print(f"✅ 记录转换结果，ID: {conv_id}")

        # 4. 模拟OCR结果
        ocr_id = db.update_ocr_result(conv_id, "/test/ocr.json", 5, 1000, 1)
        print(f"✅ 记录OCR结果，ID: {ocr_id}")

        # 5. 模拟音频转写结果
        trans_id = db.update_transcription_result(source_id, "/test/transcript.json",
                                                  "whisper", "zh", 10, 500)
        print(f"✅ 记录音频转写，ID: {trans_id}")

        # 6. 模拟对齐结果
        align_id = db.update_alignment_result(ocr_id, trans_id, "/test/alignment.json",
                                              "txt", "test", 5, 10, 4, 2)
        print(f"✅ 记录对齐结果，ID: {align_id}")

        # 7. 模拟笔记结果
        note_id = db.update_note_result(align_id, "/test/notes.md", "/test/mindmap.html",
                                        "academic", 2000)
        print(f"✅ 记录笔记结果，ID: {note_id}")

        # 8. 查询完整结果
        print(f"📊 查询完整流水线结果:")
        result = db.get_full_pipeline_result(source_id)
        if result:
            print(f"   源文件: {result['source']['filename']}")
            print(f"   状态: {result['source']['status']}")

            if 'notes' in result:
                print(f"   笔记文件: {result['notes']['markdown_file']}")

        # 9. 搜索测试
        print(f"🔍 搜索文件:")
        results = db.search_files(filename="test", limit=5)
        for r in results:
            print(f"   - {r['filename']} ({r['file_type']}): {r['status']}")

        # 关闭数据库
        db.close()

        print(f"✅ 所有测试通过!")

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # 清理测试文件
        if os.path.exists(test_file):
            os.unlink(test_file)


if __name__ == "__main__":
    """
    主函数 - 支持命令行参数
    """
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        test_database()

    elif len(sys.argv) > 3 and sys.argv[1] == "register":
        file_path = sys.argv[2]
        file_type = sys.argv[3]
        result = register_file_to_db(file_path, file_type)
        print(f"注册结果: {result}")

    elif len(sys.argv) > 2 and sys.argv[1] == "status":
        source_id = int(sys.argv[2])
        result = get_file_status(source_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif len(sys.argv) > 1 and sys.argv[1] == "search":
        filename = sys.argv[2] if len(sys.argv) > 2 else None
        file_type = sys.argv[3] if len(sys.argv) > 3 else None
        status = sys.argv[4] if len(sys.argv) > 4 else None

        result = search_files_in_db(filename, file_type, status)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        print("📋 数据库管理模块 - 用法:")
        print("  1. 测试: python db_manager.py test")
        print("  2. 注册文件: python db_manager.py register 文件路径 文件类型")
        print("  3. 查询状态: python db_manager.py status 源文件ID")
        print("  4. 搜索文件: python db_manager.py search [文件名] [文件类型] [状态]")