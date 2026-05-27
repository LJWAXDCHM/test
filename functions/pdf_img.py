from popdf import pdf2imgs
import os
from pathlib import Path


def convert_pdf_to_images(pdf_path, output_base_dir=None):
    """
    将PDF文件转换为图片序列

    参数：
    pdf_path (str): PDF文件的路径
    output_base_dir (str): 输出基础目录，默认为"output"

    返回：
    dict: 包含转换结果信息的字典
    """
    # 检查是否安装了popdf
    try:
        from popdf import pdf2imgs
    except ImportError:
        print("❌ 未安装 popdf，正在安装...")
        import subprocess
        subprocess.check_call(["pip", "install", "popdf"])
        from popdf import pdf2imgs

    # 检查文件是否存在
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF文件不存在: {pdf_path}")

    # 验证文件扩展名
    pdf_path_obj = Path(pdf_path)
    if pdf_path_obj.suffix.lower() != '.pdf':
        raise ValueError(f"不支持的文件类型: {pdf_path_obj.suffix}，仅支持.pdf格式")

    if output_base_dir is None:
        try:
            from config import Config
            # 使用config中的统一输出路径
            output_base_dir = Config.get_output_path("pdf")
        except ImportError:
            # 如果config.py不存在，使用默认路径
            output_base_dir = "output/pdf"
            print("⚠️ 未找到config.py，使用默认输出路径: output/pdf")

    # 构建输出路径：output_base_dir/pdf/文件名（不带扩展名）/
    pdf_name = pdf_path_obj.stem  # 获取文件名（不带扩展名）
    output_dir = Path(output_base_dir) / pdf_name

    # 创建输出目录
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"转换: {pdf_path}")
    print(f"保存到: {output_dir}")

    try:
        # 核心转换
        pdf2imgs(
            str(pdf_path),  # 第1个参数：输入路径
            str(output_dir)  # 第2个参数：输出路径
        )

        # 获取当前目录下的所有图片文件
        image_extensions = {'.jpg', '.jpeg', '.png', '.bmp'}
        img_files = []
        for file_path in output_dir.iterdir():
            if file_path.suffix.lower() in image_extensions and file_path.is_file():
                img_files.append(file_path)

        # 按文件名排序
        img_files = sorted(img_files, key=lambda x: x.name.lower())

        # 按顺序重命名图片文件
        renamed_count = 0
        for i, img_file in enumerate(img_files):
            new_name = f"{i:03d}{img_file.suffix}"  # 格式化为000.jpg, 001.jpg...
            new_path = output_dir / new_name

            # 如果文件名不同，尝试重命名
            if img_file.name != new_name:
                try:
                    # 如果目标文件已存在，先删除
                    if new_path.exists():
                        new_path.unlink()
                    img_file.rename(new_path)
                    renamed_count += 1
                except Exception as rename_error:
                    print(f"⚠️ 重命名 {img_file.name} 失败: {rename_error}")

        if renamed_count > 0:
            print(f"重命名了 {renamed_count} 个文件")

        # 重新获取重命名后的文件列表
        final_img_files = []
        for file_path in sorted(output_dir.iterdir()):
            if file_path.suffix.lower() in image_extensions and file_path.is_file():
                final_img_files.append(file_path)

        # 统计结果
        img_count = len(final_img_files)
        print(f"✅ PDF转换完成，生成 {img_count} 张图片")

        return {
            "success": True,
            "input_file": str(pdf_path),
            "output_dir": str(output_dir),
            "image_files": [str(f) for f in final_img_files],
            "image_count": img_count
        }

    except Exception as e:
        print(f"❌ 转换失败: {e}")
        return {
            "success": False,
            "input_file": str(pdf_path),
            "error": str(e)
        }


def convert_pdf_popdf():
    """
    原有的convert_pdf_popdf函数，用于向后兼容
    可以直接调用这个函数使用原路径
    """
    # 保持原有硬编码路径
    PDF_PATH = r"D:\Python in school\try_project\smart_note\test_data\DM_20260415110819_001.pdf"
    OUTPUT_DIR = None

    return convert_pdf_to_images(PDF_PATH, OUTPUT_DIR)


if __name__ == "__main__":
    """
    主函数用于测试
    """
    # 测试路径（可以根据需要修改）
    test_pdf_path = r"C:\Users\xdchm\Desktop\DM_20260415110819_001.pdf"
    test_output_base = None

    # 检查测试文件是否存在
    if not os.path.exists(test_pdf_path):
        print(f"❌ 测试文件不存在: {test_pdf_path}")
        print("请修改 test_pdf_path 为有效的PDF文件路径")
    else:
        print("=" * 50)
        print("PDF转图片工具 - 测试模式")
        print("=" * 50)

        result = convert_pdf_to_images(test_pdf_path, test_output_base)

        if result["success"]:
            print(f"\n转换详情：")
            print(f"- 输入文件: {result['input_file']}")
            print(f"- 输出目录: {result['output_dir']}")
            print(f"- 图片数量: {result['image_count']}")

            # 显示前几个文件路径
            if result["image_files"]:
                print(f"\n前3张图片：")
                for i, img_path in enumerate(result["image_files"][:3]):
                    print(f"  {i + 1}. {os.path.basename(img_path)}")
                if len(result["image_files"]) > 3:
                    print(f"  ... 还有 {len(result['image_files']) - 3} 张图片")
        else:
            print(f"\n❌ 转换失败: {result['error']}")