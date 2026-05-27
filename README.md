
# 🤖 智能笔记系统 (Smart Note)

将 PDF/PPT 课件与课堂/会议音频自动转换为结构化笔记与交互式思维导图

✨ 功能特性

•   📄 多格式支持：PDF、PPT、PPTX 课件转换

•   🎵 音频转写：支持 MP3、WAV、M4A 等格式，自动语音识别

•   🧠 AI 多模态对齐：基于 GLM-4V-Flash 实现图片、文字、音频三模态对齐

•   📝 智能笔记生成：自动整理为结构化 Markdown，保留数学公式

•   🌐 交互式思维导图：基于 markmap 自动生成可折叠的知识图谱

•   🗄️ 完整数据追溯：SQLite 数据库记录全流水线处理状态

•   🖥️ Web 界面：拖拽上传、实时进度、一键下载

# 🏗️ 系统架构与流水线

核心处理流水线


PDF/PPT 文件 ──► [1. 文档转换] ──► 图片序列
                                      │
                                      ▼
                                [2. OCR提取] ──► 每页文字 + 图表标记
                                      │
音频文件 ──────► [3. 音频转写] ──► 带时间戳文本
                                      │
                                      ▼
                                [4. 内容对齐] ──► GLM-4V 分析图片+匹配音频
                                      │
                                      ▼
                                [5. 笔记生成] ──► Markdown + HTML 思维导图


技术栈

组件 技术选型

后端框架 Python + FastAPI + Uvicorn

AI 模型 GLM-4V-Flash（多模态分析）、GLM-4-Flash（文本生成）、Whisper（音频转写）

OCR 引擎 EasyOCR（中英文识别）

文档转换 popdf（PDF）、poppt（PPT/PPTX）

数据库 SQLite（WAL 模式，线程安全）

前端 原生 HTML/CSS/JS + markmap（思维导图渲染）

项目结构


smart_note/
├── functions/                # 核心功能模块目录
│   ├── frontend/             # 前端页面
│   │   ├── static/
│   │   │   └── style.css     # 页面样式文件
│   │   └── index.html        # 前端主页面
│   ├── __init__.py
│   ├── main.py               # FastAPI 应用入口
│   ├── control.py            # 调度控制器
│   ├── config.py             # 全局配置文件
│   ├── database.py           # 数据库管理
│   ├── pdf_img.py            # PDF 转图片
│   ├── ppt_img.py            # PPT 转图片
│   ├── ocr_extractor.py      # OCR 文字提取
│   ├── sound.py              # 音频转写
│   ├── aligner.py            # 多模态内容对齐
│   └── cre_note.py           # 智能笔记生成
├── output/                   # 输出文件根目录
│   ├── uploads/              # 上传文件存储
│   ├── pdf/                  # PDF 处理输出
│   ├── ppt/                  # PPT 处理输出
│   ├── ocr/                  # OCR 识别结果
│   ├── sound/                # 音频处理结果
│   ├── alignment/            # 对齐结果
│   ├── notes/                # 最终笔记
│   ├── mindmaps/             # 思维导图
│   └── database/             # 数据库文件
├── test_data/                # 测试数据
├── .env                      # 环境变量配置文件
├── .bat                      # Windows 启动脚本
└── README.md                 # 项目说明文档
└── requirements.txt                #主要依赖库


# 🚀 快速开始

1. 环境准备

1.  克隆项目
    git clone <your-repo-url>
    cd smart_note
    
2.  创建并激活 Conda 环境
    conda create -n smart_note python=3.10
    conda activate smart_note
    
3.  安装依赖
    # 使用 requirements.txt 安装
    pip install -r requirements.txt
    
    # 或手动安装
    # 安装核心依赖
    pip install fastapi uvicorn python-dotenv requests numpy jieba easyocr
    # 文档转换依赖
    pip install popdf poppt
    # 音频转写依赖
    pip install openai-whisper pillow python-multipart
    
4.  配置 API 密钥
    ◦ 复制 .env.example 为 .env 或直接创建 .env 文件。

    ◦ 在 .env 文件中填入您的智谱 AI GLM API Key：
      GLM_API_KEY=your_glm_api_key_here
      # GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/chat/completions (默认，通常无需修改)
      # OUTPUT_BASE_DIR=../output (默认，通常无需修改)
      

2. 启动服务

方式一：使用启动脚本（推荐 Windows 用户）
直接双击运行根目录下的 start.bat 脚本。

方式二：手动启动
# 激活环境
conda activate smart_note
# 启动服务
python functions/main.py

服务启动后，可以通过以下地址访问：
•   🌐 Web 界面: http://localhost:8000

•   📄 API 文档: http://localhost:8000/docs (交互式 API 文档)

📖 使用指南

Web 界面使用

1.  打开浏览器，访问 http://localhost:8000。
2.  上传文件:
    ◦   必传: 拖拽或点击上传一个 PDF 或 PPT/PPTX 课件文件。

    ◦   选传: 拖拽或点击上传一个音频文件（MP3, WAV 等）。

3.  输入笔记名称: 在“笔记名称”输入框中为本次处理任务命名。
4.  开始处理: 点击“开始处理”按钮。
5.  等待与下载: 等待处理完成（通常需要 5-20 分钟，取决于文件大小）。完成后，页面会显示下载链接，您可以下载 Markdown 笔记或在线查看交互式思维导图。

API 调用

系统提供了完整的 RESTful API，方便集成。

上传文档+音频进行处理
curl -X POST "http://localhost:8000/api/process" \
  -F "document=@课件.pdf" \
  -F "audio=@讲解.mp3" \
  -F "source_name=物理课笔记"


仅上传音频进行转写
curl -X POST "http://localhost:8000/api/process/audio-only" \
  -F "audio=@录音.mp3" \
  -F "source_name=会议记录"


查询任务状态
curl "http://localhost:8000/api/tasks/{task_id}"


获取处理历史记录
curl "http://localhost:8000/api/history?limit=10"


# 🔧 核心算法说明

1. 多模态内容对齐 (aligner.py)

这是系统的核心模块，负责将课件页面与音频讲解进行智能匹配。
•   文本相似度匹配: 使用 jieba 对 OCR 提取的页面文字和音频转写文本进行分词，计算交集比例作为基础相似度。

•   动态规划最优路径: 基于相似度矩阵，使用动态规划算法求解页面-音频段之间的全局最优对齐序列，允许页面无音频或音频无对应页面的情况。

•   视觉增强分析: 对于被标记为“图表页”的幻灯片，调用 GLM-4V-Flash 多模态大模型进行分析，提取其中的数学公式、图表描述和核心要点，极大提升对非文本内容的处理能力。

2. 智能笔记生成 (cre_note.py)

将对齐后的结构化数据转化为易读的笔记和思维导图。
•   分块处理: 将课件页面按每 3 页一组进行分块，分别调用 GLM-4-Flash 模型生成笔记内容，避免上下文过长。

•   公式与格式处理: 自动识别和处理 LaTeX 公式，并将其转换为更易读的书面格式。同时，对音频特有的讲解内容进行筛选和整合，按主题归类插入到笔记中。

•   思维导图生成: 将最终生成的 Markdown 笔记，通过 markmap 库自动渲染为可交互、可折叠的 SVG/HTML 思维导图。

# 📋 系统要求

组件 最低要求 推荐配置

操作系统 Windows 10, macOS, Linux Windows 10+/macOS 12+/Ubuntu 20.04+

Python 3.8 3.10+

内存 (RAM) 8 GB 16 GB+

磁盘空间 2 GB (用于模型缓存) 10 GB+

网络 稳定连接（用于调用 GLM API） 高速稳定连接

CUDA 可选（用于加速 EasyOCR） 11.8+ (如有 NVIDIA GPU)

# 🐛 故障排查

问题现象 可能原因与解决方案

conda activate 失败 在终端中执行 conda init 后重启终端。

EasyOCR 首次运行非常慢 正常现象，EasyOCR 正在自动下载识别模型，首次运行需等待 5-10 分钟。

GLM API 返回 429 或 1302 错误 触发 API 调用频率限制。系统已内置自动重试和等待机制，如频繁出现，请检查 API 额度或稍后再试。

Whisper 加载或转写失败 确保已安装 ffmpeg：conda install ffmpeg 或从官网下载。

端口 8000 被占用 启动脚本或程序会自动尝试递增端口（8001, 8002...）。也可手动指定端口：python main.py --port 8001

# 🙏 致谢

•   https://www.zhipu.ai/ - 提供 GLM-4V / GLM-4 大模型

•   https://openai.com/ - Whisper 语音识别模型

•   https://github.com/JaidedAI/EasyOCR - 优秀的开源 OCR 库

•   https://fastapi.tiangolo.com/ - 高性能 Python Web 框架

•   https://markmap.js.org/ - 将 Markdown 转换为思维导图的工具

📄 许可证

（此处可根据实际情况添加，例如 MIT License）

