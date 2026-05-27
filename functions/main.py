"""
main.py
智能笔记系统 FastAPI Web应用 - 线程安全修复版
"""
import asyncio
import os
import json
import shutil
import traceback
from pathlib import Path
from typing import Optional, List
from datetime import datetime
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks, Query
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import Config
from database import SmartNoteDB, get_file_status, search_files_in_db
from control import SmartNoteScheduler


# ========== 数据模型 ==========

class ProcessResponse(BaseModel):
    success: bool
    message: str
    source_id: Optional[int] = None
    task_id: Optional[str] = None
    error: Optional[str] = None


class TaskStatus(BaseModel):
    task_id: str
    status: str
    progress: int
    current_stage: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str


class FileInfo(BaseModel):
    id: int
    filename: str
    file_type: str
    upload_time: str
    status: str


class HistoryResponse(BaseModel):
    success: bool
    count: int
    results: List[FileInfo]


class PipelineResult(BaseModel):
    success: bool
    source_info: Optional[dict] = None
    processing_status: Optional[dict] = None
    pipeline_result: Optional[dict] = None
    error: Optional[str] = None


# ========== 全局任务存储 ==========
tasks_store = {}


# ========== FastAPI应用 ==========

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 智能笔记系统启动中...")
    Config.validate_config()
    yield
    print("🛑 智能笔记系统关闭")


app = FastAPI(
    title="智能笔记系统 API",
    description="PDF/PPT + 音频 → 智能笔记 & 思维导图",
    version="1.0.0",
    lifespan=lifespan
)

# 确保必要的目录存在
frontend_dir = Path("frontend")
frontend_dir.mkdir(exist_ok=True)

static_dir = Path("static")
static_dir.mkdir(exist_ok=True)

uploads_dir = Path(Config.get_output_path("uploads"))
uploads_dir.mkdir(parents=True, exist_ok=True)

output_dir = Path(Config.OUTPUT_BASE_DIR)
output_dir.mkdir(parents=True, exist_ok=True)

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件服务 - 只挂载一次
app.mount("/static", StaticFiles(directory=str(output_dir)), name="static")


# ========== 辅助函数 ==========

def generate_task_id() -> str:
    import uuid
    return str(uuid.uuid4())[:8]


def get_file_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def validate_document_file(filename: str) -> bool:
    return get_file_extension(filename) in ['.pdf', '.ppt', '.pptx']


def validate_audio_file(filename: str) -> bool:
    return get_file_extension(filename) in ['.mp3', '.wav', '.m4a', '.flac', '.aac', '.ogg', '.opus']


async def process_document_task(task_id: str, doc_path: str, audio_path: Optional[str],
                                source_name: str, file_type: str):
    """
    处理文档任务 - 修复版（线程安全）
    """
    scheduler = SmartNoteScheduler(debug_mode=True)

    def run_processing():
        try:
            print(f"🧵 线程内开始处理: {source_name}")
            result = scheduler.process_document(
                doc_path=doc_path,
                audio_path=audio_path,
                source_name=source_name,
                file_type=file_type
            )
            print(f"🧵 线程内处理完成: success={result.get('success')}")
            return result
        except Exception as e:
            error_msg = f"{str(e)}{traceback.format_exc()}"
            print(f"🧵 线程内捕获异常: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "source_name": source_name,
                "file_type": file_type
            }

    try:
        tasks_store[task_id]["status"] = "processing"
        tasks_store[task_id]["current_stage"] = "初始化"
        tasks_store[task_id]["progress"] = 5
        tasks_store[task_id]["updated_at"] = datetime.now().isoformat()

        print(f"🎯 开始处理任务 {task_id}")
        print(f"🎯 文档路径: {doc_path}")
        print(f"🎯 音频路径: {audio_path}")
        print(f"🎯 源文件名: {source_name}")
        print(f"🎯 文件类型: {file_type}")

        # 定义处理阶段
        stages = [
            {"stage": "文档转换", "progress": 20},
            {"stage": "OCR提取", "progress": 40},
            {"stage": "音频转写", "progress": 60},
            {"stage": "内容对齐", "progress": 80},
            {"stage": "笔记生成", "progress": 95}
        ]

        # 在后台线程中运行处理
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_processing)

            # 等待完成，同时更新进度
            stage_idx = 0
            while not future.done() and stage_idx < len(stages):
                await asyncio.sleep(2)

                tasks_store[task_id]["current_stage"] = stages[stage_idx]["stage"]
                tasks_store[task_id]["progress"] = stages[stage_idx]["progress"]
                tasks_store[task_id]["updated_at"] = datetime.now().isoformat()

                stage_idx += 1

            # 获取结果
            result = future.result(timeout=600)

            if result.get("success"):
                # 保存笔记文件路径到任务记录
                notes_output = result.get("notes_output", {})
                if notes_output:
                    tasks_store[task_id]["notes_path"] = notes_output.get("markdown")
                    tasks_store[task_id]["mindmap_path"] = notes_output.get("mindmap")
                    # 调试输出
                    print(f"📁 任务存储笔记路径: {notes_output.get('markdown')}")
                    print(f"📁 任务存储思维导图路径: {notes_output.get('mindmap')}")
                else:
                    # 如果没有 notes_output，尝试从 result 中直接提取
                    print(f"⚠️ notes_output 为空，尝试从 result 直接提取")
                    print(f"🔍 result 包含的键: {list(result.keys())}")

                    if "notes_path" in result and "mindmap_path" in result:
                        tasks_store[task_id]["notes_path"] = result.get("notes_path")
                        tasks_store[task_id]["mindmap_path"] = result.get("mindmap_path")
                        print(f"✅ 从 result 提取成功: {result.get('mindmap_path')}")

                # 保存 source_id 到任务记录
                doc_source_id = result.get("document_source_id")
                if doc_source_id:
                    tasks_store[task_id]["source_id"] = doc_source_id

                    # 从数据库获取最新的文件路径 - 修复：使用独立连接
                    try:
                        db = SmartNoteDB()  # 创建新的数据库实例
                        cursor = db.conn.cursor()

                        # 修正：通过关联查询找到 alignment_id
                        cursor.execute("""
                            SELECT nr.markdown_file, nr.mindmap_file, ar.id as alignment_id
                            FROM note_results nr
                            JOIN alignment_results ar ON nr.alignment_id = ar.id
                            JOIN ocr_results ocr ON ar.ocr_id = ocr.id
                            JOIN pdf_ppt_conversions pc ON ocr.conversion_id = pc.id
                            WHERE pc.source_id = ?
                            ORDER BY nr.generation_time DESC 
                            LIMIT 1
                        """, (doc_source_id,))

                        note_row = cursor.fetchone()
                        if note_row:
                            tasks_store[task_id]["db_markdown_path"] = note_row[0]
                            tasks_store[task_id]["db_mindmap_path"] = note_row[1]
                            tasks_store[task_id]["alignment_id"] = note_row[2]
                            print(f"✅ 数据库路径: markdown={note_row[0]}, mindmap={note_row[1]}, alignment_id={note_row[2]}")

                        db.close()
                    except Exception as e:
                        print(f"⚠️ 获取数据库路径失败: {e}")
                        print(f"⚠️ 错误详情: {traceback.format_exc()}")

            # 详细日志
            print(f"🎯 调度器返回结果:")
            print(f"🎯 成功状态: {result.get('success')}")
            if not result.get('success'):
                print(f"🎯 错误详情: {result.get('error', '无错误信息')[:500]}")
            print(f"🎯 所有键: {list(result.keys()) if isinstance(result, dict) else '非字典'}")

        # 更新任务状态
        if result.get("success"):
            tasks_store[task_id]["status"] = "completed"
            tasks_store[task_id]["progress"] = 100
            tasks_store[task_id]["result"] = result
            tasks_store[task_id]["current_stage"] = "完成"
            print(f"✅ 任务 {task_id} 完成")
        else:
            tasks_store[task_id]["status"] = "failed"
            error_msg = result.get("error", "处理失败，未知错误")
            tasks_store[task_id]["error"] = error_msg
            tasks_store[task_id]["current_stage"] = "处理失败"
            print(f"❌ 任务 {task_id} 失败: {error_msg[:500]}")

    except Exception as e:
        error_detail = f"{str(e)}{traceback.format_exc()}"
        tasks_store[task_id]["status"] = "failed"
        tasks_store[task_id]["error"] = error_detail
        tasks_store[task_id]["current_stage"] = "系统异常"
        print(f"❌ 任务异常: {error_detail}")
    finally:
        scheduler.close()
        tasks_store[task_id]["updated_at"] = datetime.now().isoformat()


async def process_audio_only_task(task_id: str, audio_path: str, source_name: str):
    """处理纯音频任务"""
    scheduler = SmartNoteScheduler(debug_mode=True)

    def run_processing():
        try:
            return scheduler.process_audio_only(audio_path=audio_path, source_name=source_name)
        except Exception as e:
            return {
                "success": False,
                "error": f"{str(e)}{traceback.format_exc()}"
            }

    try:
        tasks_store[task_id]["status"] = "processing"
        tasks_store[task_id]["current_stage"] = "音频转写"
        tasks_store[task_id]["progress"] = 10

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_processing)

            progress = 10
            while not future.done():
                await asyncio.sleep(2)
                progress = min(progress + 10, 90)
                tasks_store[task_id]["progress"] = progress
                tasks_store[task_id]["updated_at"] = datetime.now().isoformat()

            result = future.result(timeout=400)

        if result.get("success"):
            tasks_store[task_id]["status"] = "completed"
            tasks_store[task_id]["progress"] = 100
            tasks_store[task_id]["result"] = result
            tasks_store[task_id]["current_stage"] = "完成"
        else:
            tasks_store[task_id]["status"] = "failed"
            tasks_store[task_id]["error"] = result.get("error", "音频处理失败")

    except Exception as e:
        tasks_store[task_id]["status"] = "failed"
        tasks_store[task_id]["error"] = f"{str(e)}{traceback.format_exc()}"
    finally:
        scheduler.close()
        tasks_store[task_id]["updated_at"] = datetime.now().isoformat()


# ========== API路由 ==========

@app.get("/", response_class=HTMLResponse)
async def root():
    """返回前端页面"""
    try:
        with open("frontend/index.html", "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        return HTMLResponse(content="""
        <!DOCTYPE html>
        <html>
        <head><title>智能笔记系统</title></head>
        <body>
            <h1>🤖 智能笔记系统 API</h1>
            <p>PDF/PPT + 音频 → 智能笔记 & 思维导图</p>
            <h2>API文档：<a href="/docs">/docs</a></h2>
        </body>
        </html>
        """)


@app.post("/api/process", response_model=ProcessResponse)
async def process_document(
        background_tasks: BackgroundTasks,
        document: UploadFile = File(..., description="PDF或PPT文件"),
        audio: Optional[UploadFile] = File(None, description="音频文件（可选）"),
        source_name: Optional[str] = Form(None, description="自定义源文件名")
):
    """上传文档和音频进行处理"""
    try:
        if not validate_document_file(document.filename):
            raise HTTPException(status_code=400, detail="不支持的文档格式，仅支持PDF、PPT、PPTX")

        if audio and not validate_audio_file(audio.filename):
            raise HTTPException(status_code=400, detail="不支持的音频格式")

        if not source_name:
            source_name = Path(document.filename).stem

        upload_dir = Path(Config.get_output_path("uploads"))
        upload_dir.mkdir(parents=True, exist_ok=True)

        doc_path = upload_dir / document.filename
        with open(doc_path, "wb") as f:
            shutil.copyfileobj(document.file, f)

        audio_path = None
        if audio:
            audio_path = upload_dir / audio.filename
            with open(audio_path, "wb") as f:
                shutil.copyfileobj(audio.file, f)

        file_type = "pdf" if get_file_extension(document.filename) == ".pdf" else "ppt"

        task_id = generate_task_id()
        now = datetime.now().isoformat()

        tasks_store[task_id] = {
            "task_id": task_id,
            "status": "pending",
            "progress": 0,
            "current_stage": "等待处理",
            "source_name": source_name,
            "file_type": file_type,
            "has_audio": audio is not None,
            "created_at": now,
            "updated_at": now,
            "result": None,
            "error": None
        }

        background_tasks.add_task(
            process_document_task,
            task_id,
            str(doc_path),
            str(audio_path) if audio_path else None,
            source_name,
            file_type
        )

        return ProcessResponse(
            success=True,
            message="任务已创建，正在后台处理",
            task_id=task_id
        )

    except HTTPException:
        raise
    except Exception as e:
        return ProcessResponse(
            success=False,
            message="创建任务失败",
            error=f"{str(e)}{traceback.format_exc()}"
        )


@app.post("/api/process/audio-only", response_model=ProcessResponse)
async def process_audio_only(
        background_tasks: BackgroundTasks,
        audio: UploadFile = File(..., description="音频文件"),
        source_name: Optional[str] = Form(None, description="自定义源文件名")
):
    """仅上传音频进行转写"""
    try:
        if not validate_audio_file(audio.filename):
            raise HTTPException(status_code=400, detail="不支持的音频格式")

        if not source_name:
            source_name = Path(audio.filename).stem

        upload_dir = Path(Config.get_output_path("uploads"))
        upload_dir.mkdir(parents=True, exist_ok=True)

        audio_path = upload_dir / audio.filename
        with open(audio_path, "wb") as f:
            shutil.copyfileobj(audio.file, f)

        task_id = generate_task_id()
        now = datetime.now().isoformat()

        tasks_store[task_id] = {
            "task_id": task_id,
            "status": "pending",
            "progress": 0,
            "current_stage": "等待处理",
            "source_name": source_name,
            "file_type": "audio",
            "has_audio": True,
            "created_at": now,
            "updated_at": now,
            "result": None,
            "error": None
        }

        background_tasks.add_task(
            process_audio_only_task,
            task_id,
            str(audio_path),
            source_name
        )

        return ProcessResponse(
            success=True,
            message="音频转写任务已创建",
            task_id=task_id
        )

    except HTTPException:
        raise
    except Exception as e:
        return ProcessResponse(
            success=False,
            message="创建任务失败",
            error=str(e)
        )


@app.get("/api/tasks/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    """查询任务状态和进度"""
    if task_id not in tasks_store:
        raise HTTPException(status_code=404, detail="任务不存在")

    task = tasks_store[task_id]
    return TaskStatus(
        task_id=task_id,
        status=task["status"],
        progress=task["progress"],
        current_stage=task.get("current_stage"),
        result=task.get("result"),
        error=task.get("error"),
        created_at=task["created_at"],
        updated_at=task["updated_at"]
    )


@app.get("/api/history", response_model=HistoryResponse)
async def get_history(
        file_type: Optional[str] = Query(None, description="文件类型筛选: pdf/ppt/audio"),
        status: Optional[str] = Query(None, description="状态筛选"),
        limit: int = Query(50, ge=1, le=100),
        search: Optional[str] = Query(None, description="文件名搜索关键词")
):
    """查询处理历史记录"""
    try:
        result = search_files_in_db(
            filename=search,
            file_type=file_type,
            status=status,
            limit=limit
        )

        if result.get("success"):
            file_list = [
                FileInfo(
                    id=r["id"],
                    filename=r["filename"],
                    file_type=r["file_type"],
                    upload_time=r["upload_time"],
                    status=r["status"]
                )
                for r in result["results"]
            ]
            return HistoryResponse(success=True, count=len(file_list), results=file_list)
        else:
            return HistoryResponse(
                success=False,
                count=0,
                results=[],
                error=result.get("error")
            )
    except Exception as e:
        return HistoryResponse(
            success=False,
            count=0,
            results=[],
            error=str(e)
        )


@app.get("/api/files/{source_id}", response_model=PipelineResult)
async def get_file_details(source_id: int):
    """查询单个文件的详细处理结果"""
    try:
        result = get_file_status(source_id)
        if result.get("success"):
            return PipelineResult(
                success=True,
                source_info=result.get("source_info"),
                processing_status=result.get("processing_status"),
                pipeline_result=result.get("pipeline_result")
            )
        else:
            raise HTTPException(status_code=404, detail=result.get("error", "文件不存在"))
    except HTTPException:
        raise
    except Exception as e:
        return PipelineResult(success=False, error=str(e))


@app.get("/api/download/notes/{filename}")
async def download_notes(filename: str, source_name: str = Query(..., description="源文件名")):
    """下载生成的Markdown笔记文件 - 修复版（线程安全）"""
    try:
        file_path = None
        source_id = None

        # 方法1：从数据库查询真实路径 - 修复：使用独立连接
        try:
            db = SmartNoteDB()
            cursor = db.conn.cursor()

            # 查找source_id
            cursor.execute("""
                SELECT id FROM source_files 
                WHERE filename LIKE ? OR filename LIKE ?
                ORDER BY upload_time DESC LIMIT 1
            """, (f"%{source_name}%", f"{source_name}%"))

            source_row = cursor.fetchone()
            if source_row:
                source_id = source_row[0]
                print(f"✅ 找到source_id: {source_id}")

                # 复杂的关联查询
                cursor.execute("""
                    SELECT nr.markdown_file 
                    FROM note_results nr
                    JOIN alignment_results ar ON nr.alignment_id = ar.id
                    JOIN ocr_results ocr ON ar.ocr_id = ocr.id
                    JOIN pdf_ppt_conversions pc ON ocr.conversion_id = pc.id
                    WHERE pc.source_id = ?
                    ORDER BY nr.generation_time DESC 
                    LIMIT 1
                """, (source_id,))

                note_row = cursor.fetchone()
                if note_row and note_row[0]:
                    db_path = Path(note_row[0])
                    if db_path.exists():
                        file_path = db_path
                        print(f"✅ 从数据库找到笔记路径: {file_path}")

            db.close()
        except Exception as db_err:
            print(f"⚠️ 数据库查询异常: {db_err}")

        # 方法2：从任务存储中查找
        if (not file_path or not file_path.exists()) and source_id:
            for task_id, task in tasks_store.items():
                if task.get("source_id") == source_id:
                    if task.get("db_markdown_path"):
                        db_path = Path(task["db_markdown_path"])
                        if db_path.exists():
                            file_path = db_path
                            print(f"✅ 从任务存储找到笔记路径: {file_path}")
                            break
                    elif task.get("notes_path"):
                        task_path = Path(task["notes_path"])
                        if task_path.exists():
                            file_path = task_path
                            print(f"✅ 从任务存储找到笔记路径: {file_path}")
                            break

        # 方法3：如果数据库没找到，搜索文件系统
        if not file_path or not file_path.exists():
            # 搜索标准路径
            notes_base = Path(Config.get_output_path("notes"))

            # 尝试可能的子目录
            possible_dirs = [
                notes_base / "pdf" / source_name,
                notes_base / "ppt" / source_name,
                notes_base / source_name,
                Path(Config.OUTPUT_BASE_DIR) / source_name
            ]

            for dir_path in possible_dirs:
                if dir_path.exists():
                    # 先找完全匹配的文件名
                    exact_match = dir_path / filename
                    if exact_match.exists():
                        file_path = exact_match
                        break

                    # 找任何.md文件
                    for md_file in dir_path.glob("*.md"):
                        if source_name in md_file.stem or "notes" in md_file.stem:
                            file_path = md_file
                            break

                    if file_path:
                        break

        # 方法4：全盘搜索
        if not file_path or not file_path.exists():
            search_patterns = [
                f"*{source_name}*.md",
                f"*notes*{source_name}*.md",
                f"*{source_name}*notes*.md"
            ]

            for pattern in search_patterns:
                for root, dirs, files in os.walk(Path(Config.OUTPUT_BASE_DIR)):
                    for file in files:
                        if file.endswith(".md") and source_name in file:
                            found_path = Path(root) / file
                            file_path = found_path
                            print(f"✅ 全盘搜索找到: {file_path}")
                            break
                    if file_path:
                        break
                if file_path:
                    break

        if not file_path or not file_path.exists():
            debug_info = {
                "filename": filename,
                "source_name": source_name,
                "source_id": source_id,
                "output_base": Config.OUTPUT_BASE_DIR,
                "notes_base": Config.get_output_path("notes")
            }
            print(f"❌ 未找到笔记文件: {json.dumps(debug_info, ensure_ascii=False)}")
            raise HTTPException(
                status_code=404,
                detail=f"找不到笔记文件。文件名: {filename}, 源名: {source_name}"
            )

        print(f"✅ 找到笔记文件: {file_path}")
        return FileResponse(
            path=str(file_path),
            filename=file_path.name,
            media_type="text/markdown"
        )

    except HTTPException:
        raise
    except Exception as e:
        error_msg = f"{str(e)}{traceback.format_exc()}"
        print(f"❌ 下载异常: {error_msg}")
        raise HTTPException(status_code=500, detail=f"下载失败: {str(e)}")


@app.get("/api/view/mindmap/{filename}")
async def view_mindmap(filename: str, source_name: str = Query(..., description="源文件名")):
    """查看思维导图HTML文件 - 增强查找和错误处理"""
    try:
        file_path = None

        # 方法1：数据库查询（多策略）
        try:
            db = SmartNoteDB()
            cursor = db.conn.cursor()

            # 宽松匹配source_id
            cursor.execute("""
                SELECT id FROM source_files 
                WHERE filename LIKE ? OR filename LIKE ? OR ? LIKE filename || '%'
                ORDER BY upload_time DESC LIMIT 5
            """, (f"%{source_name}%", f"{source_name}%", source_name))

            for row in cursor.fetchall():
                sid = row[0]
                # 策略A：标准关联查询
                cursor.execute("""
                    SELECT nr.mindmap_file, nr.markdown_file
                    FROM note_results nr
                    JOIN alignment_results ar ON nr.alignment_id = ar.id
                    JOIN ocr_results ocr ON ar.ocr_id = ocr.id
                    JOIN pdf_ppt_conversions pc ON ocr.conversion_id = pc.id
                    WHERE pc.source_id = ? AND nr.mindmap_file IS NOT NULL
                    ORDER BY nr.generation_time DESC LIMIT 1
                """, (sid,))
                note_row = cursor.fetchone()

                if note_row:
                    if note_row[0] and Path(note_row[0]).exists():
                        file_path = Path(note_row[0])
                        break
                    # 从markdown推导
                    if note_row[1] and Path(note_row[1]).exists():
                        inferred = Path(note_row[1]).with_suffix('').as_posix() + "_mindmap.html"
                        if Path(inferred).exists():
                            file_path = Path(inferred)
                            break

            db.close()
        except Exception as e:
            print(f"⚠️ 数据库查询异常: {e}")

        # 方法2：文件系统搜索（增强）
        if not file_path:
            search_bases = [
                Path(Config.OUTPUT_BASE_DIR),
                Path(Config.get_output_path("notes")),
                Path("output"), Path(".")
            ]

            for base in search_bases:
                if not base.exists(): continue
                # 直接匹配
                direct = base / filename
                if direct.exists():
                    file_path = direct
                    break
                # 递归搜索
                for html_file in base.rglob("*.html"):
                    if "mindmap" in html_file.name.lower() and source_name.lower() in html_file.name.lower():
                        file_path = html_file
                        break
                if file_path: break

        if not file_path or not file_path.exists():
            raise HTTPException(status_code=404, detail=f"思维导图不存在: {source_name}")

        with open(file_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"加载失败: {str(e)}")

@app.get("/api/download/transcript/{filename}")
async def download_transcript(filename: str):
    """下载音频转写JSON文件"""
    try:
        transcript_dir = Path(Config.get_output_path("sound"))
        file_path = transcript_dir / filename

        if not file_path.exists():
            raise HTTPException(status_code=404, detail="转写文件不存在")

        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type="application/json"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """删除任务记录"""
    if task_id not in tasks_store:
        raise HTTPException(status_code=404, detail="任务不存在")

    del tasks_store[task_id]
    return JSONResponse(content={"success": True, "message": "任务已删除"})


@app.get("/api/stats")
async def get_system_stats():
    """获取系统统计信息 - 修复版（线程安全）"""
    try:
        db = SmartNoteDB()  # 创建新的数据库实例
        cursor = db.conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM source_files")
        total_files = cursor.fetchone()[0]

        cursor.execute("SELECT file_type, COUNT(*) FROM source_files GROUP BY file_type")
        type_stats = {row[0]: row[1] for row in cursor.fetchall()}

        cursor.execute("SELECT status, COUNT(*) FROM source_files GROUP BY status")
        status_stats = {row[0]: row[1] for row in cursor.fetchall()}

        db.close()

        return {
            "success": True,
            "stats": {
                "total_files": total_files,
                "by_type": type_stats,
                "by_status": status_stats,
                "active_tasks": len([t for t in tasks_store.values() if t["status"] == "processing"])
            }
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)