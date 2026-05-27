import os
from poppt import ppt2img
from pathlib import Path


def convert_ppt_to_images(ppt_path, output_base_dir=None):





    """
    将PPT/PPTX文件转换为图片序列

    参数：
    ppt_path (str): PPT文件的路径
    output_base_dir (str): 输出基础目录，默认为"output"

    返回：
    dict: 包含转换结果信息的字典
    """
    # 检查文件是否存在
    if not os.path.exists(ppt_path):
        raise FileNotFoundError(f"PPT文件不存在: {ppt_path}")

    # 验证文件扩展名
    ppt_path_obj = Path(ppt_path)
    if ppt_path_obj.suffix.lower() not in ['.ppt', '.pptx']:
        raise ValueError(f"不支持的文件类型: {ppt_path_obj.suffix}，仅支持.ppt和.pptx格式")

        # 如果未指定输出目录，则从config.py获取
    if output_base_dir is None:
        try:
            from config import Config
            # 使用config中的统一输出路径
            output_base_dir = Config.get_output_path("ppt")
        except ImportError:
            # 如果config.py不存在，使用默认路径
            output_base_dir = "output/ppt"
            print("⚠️ 未找到config.py，使用默认输出路径: output/ppt")

    # 构建输出路径：output_base_dir/ppt/文件名（不带扩展名）/
    ppt_name = ppt_path_obj.stem  # 获取文件名（不带扩展名）
    output_dir = Path(output_base_dir) / ppt_name

    # 创建输出目录
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"转换: {ppt_path}")
    print(f"保存到: {output_dir}")

    try:
        # 执行转换
        ppt2img(
            input_path=str(ppt_path),
            output_path=str(output_dir)
        )

        # 获取所有图片文件
        image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif'}
        img_files = []
        for file_path in output_dir.iterdir():
            if file_path.suffix.lower() in image_extensions and file_path.is_file():
                img_files.append(file_path)

        # 按字母顺序排序
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

        print(f"✅ 转换成功，生成 {len(final_img_files)} 张图片")

        return {
            "success": True,
            "input_file": str(ppt_path),
            "output_dir": str(output_dir),
            "image_files": [str(f) for f in final_img_files],
            "image_count": len(final_img_files)
        }

    except Exception as e:
        print(f"❌ 转换失败: {e}")
        return {
            "success": False,
            "input_file": str(ppt_path),
            "error": str(e)
        }


def main():
    """
    原有的main函数，用于向后兼容和独立测试
    使用时可以修改测试路径
    """
    # 测试路径（可以根据需要修改）
    test_ppt_path = r"D:\Python in school\try_project\smart_note\test_data\测试.pptx"
    test_output_base = None

    # 检查测试文件是否存在
    if not os.path.exists(test_ppt_path):
        print(f"❌ 测试文件不存在: {test_ppt_path}")
        print("请修改 test_ppt_path 为有效的PPT文件路径")
        return

    print("=" * 50)
    print("PPT转图片工具 - 测试模式")
    print("=" * 50)

    result = convert_ppt_to_images(test_ppt_path, test_output_base)

    if result["success"]:
        print(f"\n转换详情：")
        print(f"- 输入文件: {result['input_file']}")
        print(f"- 输出目录: {result['output_dir']}")


        # 显示前几个文件路径
        if result["image_files"]:
            print(f"\n前3张图片：")
            for i, img_path in enumerate(result["image_files"][:3]):
                print(f"  {i + 1}. {os.path.basename(img_path)}")
            if len(result["image_files"]) > 3:
                print(f"  ... 还有 {len(result['image_files']) - 3} 张图片")
    else:
        print(f"\n❌ 转换失败: {result['error']}")


if __name__ == "__main__":
    main()