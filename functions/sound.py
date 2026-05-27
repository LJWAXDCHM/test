import whisper
import json
import os
from pathlib import Path


def format_time(seconds):
    """秒数转 mm:ss"""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def transcribe_audio(audio_path, output_base_dir="output", model_size="small", language=None):
    """
    将音频文件转写为文字

    参数：
    audio_path (str): 音频文件路径
    output_base_dir (str): 输出基础目录，默认为"output"
    model_size (str): Whisper模型大小，可选："tiny", "base", "small", "medium", "large"，默认为"medium"
    language (str): 音频语言代码，为None时自动检测（默认自动检测）

    返回：
    dict: 包含转写结果信息的字典
    """
    # 检查文件是否存在
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"音频文件不存在: {audio_path}")

    # 验证音频文件格式
    audio_path_obj = Path(audio_path)
    audio_ext = audio_path_obj.suffix.lower()
    supported_exts = {'.mp3', '.wav', '.m4a', '.flac', '.aac', '.ogg', '.opus'}

    # 如果未指定输出目录，则从config.py获取
    if output_base_dir is None:
        try:
            from config import Config
            # 使用config中的统一输出路径
            output_base_dir = Config.get_output_path("sound")
        except ImportError:
            # 如果config.py不存在，使用默认路径
            output_base_dir = "output/sound"
            print("⚠️ 未找到config.py，使用默认输出路径: output/sound")
            # 确保目录存在
            Path(output_base_dir).mkdir(parents=True, exist_ok=True)

    # 构建输出路径：output_base_dir/sound/文件名（不带扩展名）/
    audio_name = audio_path_obj.stem  # 获取文件名（不带扩展名）
    output_dir = Path(output_base_dir)

    # 创建输出目录
    output_dir.mkdir(parents=True, exist_ok=True)

    # 输出文件名
    output_filename = f"{audio_name}_transcript.json"
    output_path = output_dir / output_filename

    print(f"正在加载 Whisper 模型 ({model_size})...")
    try:
        model = whisper.load_model(model_size)
        print("模型加载完成！")
    except Exception as e:
        raise RuntimeError(f"加载Whisper模型失败: {e}")

    print(f"开始转写: {audio_path}")
    print(f"输出文件: {output_path}")

    try:
        # 执行转写（自动检测语言）
        print("正在自动检测语言并转写...")
        result = model.transcribe(str(audio_path))

        # 整理结果（带时间戳）
        segments = []
        for seg in result["segments"]:
            segments.append({
                "start": format_time(seg["start"]),
                "end": format_time(seg["end"]),
                "text": seg["text"].strip()
            })

        # 构建输出数据
        output_data = {
            "audio_file": str(audio_path),
            "model_used": model_size,
            "language": result.get("language", "auto-detected"),
            "full_text": result["text"],
            "segment_count": len(segments),
            "segments": segments
        }

        # 保存为 JSON
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)

        print(f"✅ 转写完成！保存到: {output_path}")
        print(f"📊 检测到语言: {output_data['language']}")
        print(f"📊 分段数: {len(segments)}")
        print(f"📊 总字数: {len(result['text'])}")

        return {
            "success": True,
            "input_file": str(audio_path),
            "output_file": str(output_path),
            "model": model_size,
            "language": output_data["language"],
            "full_text": result["text"],
            "segments": segments,
            "segment_count": len(segments)
        }

    except Exception as e:
        print(f"❌ 转写失败: {e}")
        return {
            "success": False,
            "input_file": str(audio_path),
            "error": str(e)
        }


def quick_transcribe():
    """
    快速转写函数，用于向后兼容
    使用原硬编码路径进行测试
    """
    # 保持原有硬编码路径
    audio_file = r"D:\Python in school\try_project\smart_note\test_data\英语六级音频.mp3"
    output_dir = r"D:\Python in school\try_project\smart_note\output"

    # 使用medium模型，自动检测语言
    return transcribe_audio(audio_file, output_dir, model_size="medium")


if __name__ == "__main__":
    """
    主函数用于测试
    """
    # 测试路径（可以根据需要修改）
    test_audio_path = r"D:\Python in school\try_project\smart_note\test_data\物理学史_中国大学MOOC_慕课.mp3"
    test_output_base = None

    # 检查测试文件是否存在
    if not os.path.exists(test_audio_path):
        print(f"❌ 测试文件不存在: {test_audio_path}")
        print("请修改 test_audio_path 为有效的音频文件路径")
    else:
        print("=" * 50)
        print("Whisper 音频转写工具")
        print("=" * 50)
        print(f"📌 使用设置：")
        print(f"  - 模型: small (推荐模型，平衡准确性与速度)")
        print(f"  - 语言: 自动检测")
        print(f"  - 输出目录: {test_output_base}/sound/")
        print("-" * 50)

        result = transcribe_audio(test_audio_path, test_output_base)

        if result["success"]:
            print(f"\n✅ 转写详情：")
            print(f"- 输入文件: {result['input_file']}")
            print(f"- 输出文件: {result['output_file']}")
            print(f"- 使用模型: {result['model']}")
            print(f"- 检测语言: {result['language']}")
            print(f"- 分段数量: {result['segment_count']}")

            # 显示前几段文字
            if result["segments"]:
                print(f"\n📝 前3段转写内容：")
                for i, segment in enumerate(result["segments"][:3]):
                    print(f"  [{segment['start']}-{segment['end']}] {segment['text']}")

                if len(result["segments"]) > 3:
                    print(f"  ... 还有 {len(result['segments']) - 3} 段")

            print(f"\n📄 完整文本预览（前200字符）：")
            print(result["full_text"][:200] + "...")
        else:
            print(f"\n❌ 转写失败: {result['error']}")