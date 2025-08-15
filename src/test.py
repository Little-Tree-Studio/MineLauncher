from MineKernel.launcher import GameLauncher
import time
launcher = GameLauncher(
    java_path="D:/Program Files/Zulu/zulu-21/bin/javaw.exe",
    game_version="1.20.4",
    minecraft_dir="E:/###游戏/Minecraft/.minecraft",
    max_memory_mb=8192,  # 8GB内存
    min_memory_mb=2048    # 2GB初始内存
)
launcher.set_jvm_argument("-XX:+UseG1GC")
launcher.set_jvm_argument("-Dlog4j2.formatMsgNoLookups", "true")

launcher.set_natives_dir("E:/###游戏/Minecraft/.minecraft/versions/1.20.4/1.20.4-natives")

launcher.add_classpath(
    "E:/###游戏/Minecraft/.minecraft/libraries/com/google/code/gson/gson/2.10.1/gson-2.10.1.jar",
    "E:/###游戏/Minecraft/.minecraft/versions/1.20.4/1.20.4.jar"
)

launcher.set_player_info(
    username="Steve",
    uuid="00000000-0000-0000-0000-000000000000",
    access_token="token123",
    user_type="msa"
)

launcher.set_window_size(1280, 720)

# 构建并查看启动命令
print(launcher.get_command_string())

# 定义日志回调
def handle_game_log(line: str):
    if "error" in line.lower():
        print(f"⚠️ 警告: {line}")
    elif "warn" in line.lower():
        print(f"🔶 注意: {line}")
    else:
        print(f"📜 {line}")

# 启动游戏（带日志回调）
success, message = launcher.launch(log_callback=handle_game_log)
if not success:
    print(f"启动失败: {message}")
    exit(1)

# 获取日志文件路径
print(f"游戏日志保存在: {launcher.get_log_file()}")

# 等待游戏结束
try:
    while launcher.is_running():
        time.sleep(1)
    print("游戏正常结束")
except KeyboardInterrupt:
    print("用户中断，终止游戏...")
    launcher.terminate()

print("游戏启动器退出")