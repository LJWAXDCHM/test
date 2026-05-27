# config.py
"""
config.py
配置文件
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class Config:
    """
    配置类
    """

    # GLM-4.6V-Flash API配置
    GLM_API_KEY = os.getenv("GLM_API_KEY", "")
    GLM_BASE_URL = os.getenv("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions")

    # 模型配置
    GLM_MODEL = "glm-4v-flash"

    # 路径配置
    PROJECT_ROOT = Path(__file__).parent.parent
    OUTPUT_BASE_DIR = os.getenv("OUTPUT_BASE_DIR", str(PROJECT_ROOT / "output"))

    # OCR配置 - 直接使用easyocr
    OCR_ENGINE = "easyocr"  # 改为easyocr
    OCR_LANG = ["ch_sim", "en"]  # EasyOCR支持的语言列表

    # 处理配置
    MAX_TOKENS = 2000
    TEMPERATURE = 0.1
    REQUEST_TIMEOUT = 60

    @classmethod
    def validate_config(cls):
        """验证配置是否完整"""
        errors = []

        if not cls.GLM_API_KEY:
            errors.append("GLM_API_KEY未设置，请在.env文件中设置或传入环境变量")

        if not os.path.exists(cls.OUTPUT_BASE_DIR):
            os.makedirs(cls.OUTPUT_BASE_DIR, exist_ok=True)

        if errors:
            for error in errors:
                print(f"⚠️ 配置警告: {error}")
            return False

        return True

    @classmethod
    def get_output_path(cls, *subdirs):
        """获取输出路径"""
        path = Path(cls.OUTPUT_BASE_DIR)
        for subdir in subdirs:
            path = path / subdir
        path.mkdir(parents=True, exist_ok=True)
        return str(path)


# 创建必要的输出目录
OUTPUT_DIRS = [
    "pdf",       # PDF转图片输出
    "ppt",       # PPT转图片输出
    "ocr",       # OCR提取结果
    "alignment", # 对齐结果
    "notes",     # 笔记输出
    "mindmaps",  # 思维导图输出
    "sound"      # 音频处理输出
]

for dir_name in OUTPUT_DIRS:
    dir_path = Config.get_output_path(dir_name)
    print(f"✅ 确保输出目录存在: {dir_path}")