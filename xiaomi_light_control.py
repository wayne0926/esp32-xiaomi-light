#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
米家智能灯局域网控制脚本

支持功能:
- 电源开关
- 亮度调节 (0-100)
- 色温调节 (Kelvin)
- 情景模式
- 读取设备状态

用法:
    python3 xiaomi_light_control.py on              # 开灯
    python3 xiaomi_light_control.py off             # 关灯
    python3 xiaomi_light_control.py toggle          # 切换状态
    python3 xiaomi_light_control.py status          # 查看完整状态
    python3 xiaomi_light_control.py bright 80       # 设置亮度80%
    python3 xiaomi_light_control.py ct 4000         # 设置色温4000K
    python3 xiaomi_light_control.py scene night     # 情景模式: night/movie/brightness
    python3 xiaomi_light_control.py probe           # 探测设备所有属性
"""

import sys
import argparse
import time
from miio import MiotDevice

# ============== 设备配置 ==============
CONFIG = {
    "ip": "192.168.x.x",           # 设备IP
    "token": "YOUR_DEVICE_TOKEN_HEX",  # 设备Token
}

# ============== MIoT siid/piid 定义 ==============
# daolai.light.dls006 设备属性定义
PROPERTIES = {
    # 主灯服务 (siid=2)
    "power": (2, 1),          # 电源开关: True/False
    "brightness": (2, 2),     # 亮度: 0-100
    "color_temp": (2, 3),    # 色温: Kelvin (约2500-9000)
    "mode": (2, 4),           # 模式: 0=日光, 1=月光, 2=彩光, 3=节能等

    # 彩灯服务 (siid=3) - 如果设备支持
    "color_power": (3, 1),     # 彩灯电源
    "color_brightness": (3, 2),  # 彩灯亮度
    "color_hue": (3, 3),       # 彩灯色相 (0-360)
}

# 情景模式定义
SCENE_MODES = {
    "night": {"brightness": 10, "color_temp": 2500},
    "movie": {"brightness": 20, "color_temp": 3000},
    "bright": {"brightness": 100, "color_temp": 5000},
    "warm": {"brightness": 60, "color_temp": 2700},
    "cool": {"brightness": 70, "color_temp": 6000},
}


class XiaomiLight:
    """米家智能灯控制类"""

    def __init__(self, ip: str, token: str):
        self.device = MiotDevice(ip, token)
        print(f"已连接到设备: {ip}")

    # ==================== 电源控制 ====================

    def set_power(self, on: bool) -> bool:
        """设置电源状态"""
        siid, piid = PROPERTIES["power"]
        result = self.device.set_property_by(siid, piid, on)
        if result and result[0].get("code") == 0:
            print(f"灯已{'打开' if on else '关闭'}")
            return True
        print(f"设置失败: {result}")
        return False

    def get_power(self) -> bool:
        """获取电源状态"""
        siid, piid = PROPERTIES["power"]
        result = self.device.get_property_by(siid, piid)
        if result:
            return result[0].get("value", False)
        return False

    def turn_on(self) -> bool:
        """开灯"""
        return self.set_power(True)

    def turn_off(self) -> bool:
        """关灯"""
        return self.set_power(False)

    def toggle(self) -> bool:
        """切换灯光状态"""
        current = self.get_power()
        return self.set_power(not current)

    # ==================== 亮度控制 ====================

    def set_brightness(self, value: int) -> bool:
        """
        设置亮度

        Args:
            value: 亮度值 0-100

        Returns:
            bool: 是否成功
        """
        siid, piid = PROPERTIES["brightness"]
        value = max(0, min(100, value))  # 限制范围
        result = self.device.set_property_by(siid, piid, value)
        if result and result[0].get("code") == 0:
            print(f"亮度已设置为: {value}%")
            return True
        print(f"设置失败: {result}")
        return False

    def get_brightness(self) -> int:
        """获取亮度"""
        siid, piid = PROPERTIES["brightness"]
        result = self.device.get_property_by(siid, piid)
        if result:
            return result[0].get("value", 0)
        return 0

    # ==================== 色温控制 ====================

    def set_color_temp(self, kelvin: int) -> bool:
        """
        设置色温

        Args:
            kelvin: 色温值，单位 Kelvin
                   常见值:
                   - 2500K: 暖黄光 (类似白炽灯)
                   - 3000K: 暖白光
                   - 4000K: 中性光
                   - 5000K: 日光
                   - 6000K: 冷白光

        Returns:
            bool: 是否成功
        """
        siid, piid = PROPERTIES["color_temp"]
        result = self.device.set_property_by(siid, piid, kelvin)
        if result and result[0].get("code") == 0:
            print(f"色温已设置为: {kelvin}K")
            return True
        print(f"设置失败: {result}")
        return False

    def get_color_temp(self) -> int:
        """获取色温 (Kelvin)"""
        siid, piid = PROPERTIES["color_temp"]
        result = self.device.get_property_by(siid, piid)
        if result:
            return result[0].get("value", 0)
        return 0

    # ==================== 情景模式 ====================

    def set_scene(self, scene_name: str) -> bool:
        """
        设置情景模式

        Args:
            scene_name: 情景名称
               - night:  夜间模式 (10%亮度, 2500K暖黄)
               - movie:  影院模式 (20%亮度, 3000K暖白)
               - bright: 明亮模式 (100%亮度, 5000K日光)
               - warm:   温馨模式 (60%亮度, 2700K暖白)
               - cool:   清爽模式 (70%亮度, 6000K冷白)

        Returns:
            bool: 是否成功
        """
        if scene_name not in SCENE_MODES:
            print(f"未知情景: {scene_name}")
            print(f"可用情景: {', '.join(SCENE_MODES.keys())}")
            return False

        scene = SCENE_MODES[scene_name]
        print(f"设置情景: {scene_name}")
        self.turn_on()
        time.sleep(0.2)
        self.set_brightness(scene["brightness"])
        time.sleep(0.2)
        self.set_color_temp(scene["color_temp"])
        return True

    # ==================== 彩灯控制 ====================

    def get_color_properties(self) -> dict:
        """获取彩灯属性 (如果支持)"""
        props = {}
        for name, (siid, piid) in PROPERTIES.items():
            if name.startswith("color_"):
                try:
                    result = self.device.get_property_by(siid, piid)
                    if result and result[0].get("code") == 0:
                        props[name] = result[0].get("value")
                except:
                    pass
        return props

    # ==================== 状态查询 ====================

    def status(self) -> dict:
        """
        获取完整状态

        Returns:
            dict: 包含电源、亮度、色温等状态
        """
        return {
            "power": self.get_power(),
            "brightness": self.get_brightness(),
            "color_temp": self.get_color_temp(),
        }

    def print_status(self):
        """打印完整状态"""
        status = self.status()
        print("\n========== 设备状态 ==========")
        print(f"电源:    {'开启' if status['power'] else '关闭'}")
        print(f"亮度:    {status['brightness']}%")

        ct = status['color_temp']
        if ct < 3000:
            ct_desc = "暖黄"
        elif ct < 4000:
            ct_desc = "暖白"
        elif ct < 5000:
            ct_desc = "中性"
        elif ct < 6000:
            ct_desc = "日光"
        else:
            ct_desc = "冷白"
        print(f"色温:    {ct}K ({ct_desc})")
        print("=" * 29)

    # ==================== 设备探测 ====================

    def probe_properties(self):
        """探测设备所有可用属性"""
        print("\n========== 探测设备属性 ==========")
        print("扫描 siid 1-10, piid 1-10...")

        found = []
        for siid in range(1, 11):
            for piid in range(1, 11):
                try:
                    result = self.device.get_property_by(siid, piid)
                    if result and result[0].get("code") == 0:
                        value = result[0].get("value")
                        value_type = type(value).__name__
                        found.append((siid, piid, value, value_type))
                        print(f"siid={siid}, piid={piid}: {value} ({value_type})")
                except:
                    pass

        print(f"\n共发现 {len(found)} 个可用属性")
        print("=" * 33)
        return found


def main():
    parser = argparse.ArgumentParser(
        description="米家智能灯控制",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 xiaomi_light_control.py on              # 开灯
  python3 xiaomi_light_control.py off             # 关灯
  python3 xiaomi_light_control.py toggle          # 切换状态
  python3 xiaomi_light_control.py status          # 查看状态
  python3 xiaomi_light_control.py bright 80       # 设置亮度80%%
  python3 xiaomi_light_control.py ct 4000         # 设置色温4000K
  python3 xiaomi_light_control.py scene night     # 夜间情景
  python3 xiaomi_light_control.py probe           # 探测设备属性

色温参考:
  2500K - 暖黄光 (白炽灯效果)
  3000K - 暖白光
  4000K - 中性光
  5000K - 日光
  6000K - 冷白光
        """
    )

    parser.add_argument("action", choices=[
        "on", "off", "toggle", "status", "bright", "ct", "scene", "probe"
    ], help="操作")
    parser.add_argument("value", nargs="?", default=None,
                        help="参数: bright=0-100, ct=色温(K), scene=情景名称")
    parser.add_argument("--ip", help="设备IP (覆盖配置)")
    parser.add_argument("--token", help="设备Token (覆盖配置)")

    args = parser.parse_args()

    # 使用命令行参数或配置文件
    ip = args.ip or CONFIG["ip"]
    token = args.token or CONFIG["token"]

    # 创建设备连接
    light = XiaomiLight(ip, token)

    # 执行操作
    if args.action == "on":
        light.turn_on()

    elif args.action == "off":
        light.turn_off()

    elif args.action == "toggle":
        light.toggle()

    elif args.action == "status":
        light.print_status()

    elif args.action == "bright":
        if args.value is None:
            print("错误: 请指定亮度值 (0-100)")
            sys.exit(1)
        try:
            value = int(args.value)
            light.set_brightness(value)
        except ValueError:
            print("错误: 亮度值必须是数字")
            sys.exit(1)

    elif args.action == "ct":
        if args.value is None:
            print("错误: 请指定色温值 (Kelvin)")
            sys.exit(1)
        try:
            value = int(args.value)
            light.set_color_temp(value)
        except ValueError:
            print("错误: 色温值必须是数字")
            sys.exit(1)

    elif args.action == "scene":
        if args.value is None:
            print("错误: 请指定情景名称")
            print(f"可用情景: {', '.join(SCENE_MODES.keys())}")
            sys.exit(1)
        light.set_scene(args.value)

    elif args.action == "probe":
        light.probe_properties()


if __name__ == "__main__":
    main()
