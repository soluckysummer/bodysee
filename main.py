"""坐姿提醒器 CLI：调用摄像头低频采样，检测脖子前倾 / 驼背 / 久坐并弹窗提醒。

用法：
    python main.py --calibrate   # 先坐正，采集 10 秒记录你的标准姿态基线
    python main.py --preview     # 实时预览关键点和角度，用于摆放摄像头（按 q 退出）
    python main.py               # 开始后台静默监控（Ctrl+C 停止）
    python main.py --show        # 监控的同时显示实时画面和角度（按 q 退出）

菜单栏常驻版本见 menubar.py。
"""

import argparse
import sys
import time
from datetime import datetime

import cv2

from config import CONFIG_PATH, load_config, save_config, resolve_side
from monitor_core import PostureMonitor, open_camera, run_calibration
from posture import PostureAnalyzer


def log(message):
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


# ---------------------------------------------------------------- 校准

def calibrate(config):
    print("== 校准模式 ==")
    print("请坐正：收下巴、耳朵对齐肩膀、背挺直，保持 10 秒...")
    try:
        cap = open_camera(config["camera_index"])
    except RuntimeError as e:
        sys.exit(str(e))
    analyzer = PostureAnalyzer()
    try:
        baseline = run_calibration(cap, analyzer, config, log=print)
    finally:
        cap.release()
        analyzer.close()

    if baseline is None:
        sys.exit("有效采样太少，没法校准。请确认摄像头能拍到你的侧面（至少头和肩膀），再试一次。")

    config["baseline"] = baseline
    save_config(config)
    print(f"\n校准完成，基线已保存: 颈部 {baseline['neck']}°"
          + (f"，躯干 {baseline['torso']}°" if baseline["torso"] is not None else "（躯干不可见，只监控颈部）")
          + f"，跟踪侧 {baseline['side']}")
    print(f"判定阈值: 颈部 > {baseline['neck'] + config['neck_delta_deg']:.1f}° 算前倾"
          + (f"，躯干 > {baseline['torso'] + config['torso_delta_deg']:.1f}° 算驼背" if baseline["torso"] is not None else ""))


# ---------------------------------------------------------------- 画面叠加

def draw_overlay(frame, result, lines):
    """在画面上画出判定用的两条线（肩→耳、髋→肩）和状态文字。"""
    if result:
        h, w = frame.shape[:2]
        px = {name: (int(x * w), int(y * h))
              for name, (x, y) in result["points"].items()}
        cv2.line(frame, px["shoulder"], px["ear"], (0, 200, 255), 3)
        if "hip" in px:
            cv2.line(frame, px["hip"], px["shoulder"], (255, 200, 0), 3)
        for pt in px.values():
            cv2.circle(frame, pt, 6, (0, 255, 0), -1)
    for i, text in enumerate(lines):
        if "BAD" in text or "!" in text:
            color = (0, 0, 255)
        elif "no person" in text:
            color = (0, 165, 255)
        else:
            color = (0, 200, 0)
        cv2.putText(frame, text, (20, 40 + i * 32),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)


# ---------------------------------------------------------------- 预览

def preview(config):
    print("== 预览模式 ==  调整摄像头位置，让画面拍到你的侧面头肩（最好含髋部）。按 q 退出。")
    try:
        cap = open_camera(config["camera_index"])
    except RuntimeError as e:
        sys.exit(str(e))
    analyzer = PostureAnalyzer()
    baseline = config.get("baseline")
    side = resolve_side(config)
    print(f"跟踪侧: {side}" + ("（校准后会锁定主导侧）" if side == "auto" else "（已锁定）"))
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            result = analyzer.analyze(frame, side=side)
            if result:
                lines = [f"side: {result['side']}"
                         + (" (locked)" if side != "auto" else ""),
                         f"neck: {result['neck']:.1f} deg"]
                if result["torso"] is not None:
                    lines.append(f"torso: {result['torso']:.1f} deg")
                if baseline:
                    neck_bad = result["neck"] > baseline["neck"] + config["neck_delta_deg"]
                    torso_bad = (baseline.get("torso") is not None and result["torso"] is not None
                                 and result["torso"] > baseline["torso"] + config["torso_delta_deg"])
                    lines.append("posture: BAD" if (neck_bad or torso_bad) else "posture: OK")
            else:
                lines = ["no person detected"]
            draw_overlay(frame, result, lines)
            cv2.imshow("posture preview", frame)
            if cv2.waitKey(60) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        analyzer.close()
        cv2.destroyAllWindows()


# ---------------------------------------------------------------- 监控

def monitor(config, show=False):
    try:
        mon = PostureMonitor(config, log=log)
    except RuntimeError:
        sys.exit("还没有校准基线。请先坐正后运行: python main.py --calibrate")

    print("== 监控模式 ==  " + ("画面窗口按 q 退出" if show else "Ctrl+C 停止"))
    print(f"采样间隔 {mon.interval}s（每次取 {mon.frames_n} 帧中位数）| 跟踪侧 {mon.side}"
          + f" | 前倾阈值 {mon.neck_limit:.1f}°"
          + (f" | 驼背阈值 {mon.torso_limit:.1f}°" if mon.torso_limit else " | 躯干未校准，不监控驼背")
          + f" | 久坐上限 {config['sit_limit_min']}min")

    try:
        mon.open()
    except RuntimeError as e:
        sys.exit(str(e))

    try:
        if show:
            # 画面持续刷新，检测仍按采样间隔执行，叠加显示最近一次的结果
            last_result, last_lines = None, ["waiting for first sample..."]
            next_sample = 0.0
            while True:
                ok, frame = mon.cap.read()
                if not ok:
                    break
                now = time.time()
                if now >= next_sample:
                    next_sample = now + mon.interval
                    last_result, last_lines = mon.step()
                draw_overlay(frame, last_result,
                             last_lines + [f"next check in {max(0, next_sample - now):.0f}s"])
                cv2.imshow("posture monitor", frame)
                if cv2.waitKey(50) & 0xFF == ord("q"):
                    break
        else:
            while True:
                mon.step()
                time.sleep(mon.interval)
    except KeyboardInterrupt:
        print("\n已停止监控。")
    finally:
        mon.close()
        if show:
            cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description="坐姿提醒器")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--calibrate", action="store_true", help="采集标准坐姿基线")
    mode.add_argument("--preview", action="store_true", help="实时预览，调整摄像头位置用")
    parser.add_argument("--show", action="store_true", help="监控时显示实时画面和角度")
    args = parser.parse_args()

    config = load_config()
    if not CONFIG_PATH.exists():
        save_config(config)

    if args.calibrate:
        calibrate(config)
    elif args.preview:
        preview(config)
    else:
        monitor(config, show=args.show)


if __name__ == "__main__":
    main()
