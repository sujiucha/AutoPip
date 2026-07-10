import os
import sys
import subprocess
import threading
from mcdreforged.api.all import *

PLUGIN_METADATA = {
    'id': 'autopip',
    'version': '3.0.0',
    'name': 'Auto Pip Installer Pro',
    'description': '提供美观、智能、易管理的MCDR插件依赖安装服务',
    'author': 'YourName',
    'link': ''
}

PREFIX = '§b[AutoPip]§r '

class Configuration(Serializable):
    pip_mirror: str = "https://pypi.tuna.tsinghua.edu.cn/simple"
    max_scan_depth: int = 2

config: Configuration
is_installing = False
install_lock = threading.Lock()

def on_load(server: PluginServerInterface, prev):
    load_config(server)
    
    server.register_help_message('!!pip', 'AutoPip 依赖管理系统', permission=3)
    
    # 命令树
    command_tree = Literal('!!pip').requires(lambda src: src.has_permission(3)).then(
        Literal('check').runs(lambda src, ctx: check_dependencies(src))
    ).then(
        Literal('install').runs(lambda src, ctx: install_dependencies(src))
    ).then(
        Literal('list').runs(lambda src, ctx: list_dependencies(src))
    ).then(
        Literal('reload').runs(lambda src, ctx: reload_config_cmd(src))
    )
    
    server.register_command(command_tree)
    server.logger.info(f'[{PLUGIN_METADATA["name"]}] V{PLUGIN_METADATA["version"]} 已加载！')

def load_config(server: PluginServerInterface):
    global config
    config = server.load_config_simple(target_class=Configuration)

def reload_config_cmd(source: CommandSource):
    """热重载配置文件"""
    load_config(source.get_server())
    source.reply(PREFIX + '§a配置文件已重新加载！')
    source.reply(PREFIX + f'当前镜像源: §7{config.pip_mirror or "官方默认"}')

def get_requirements_files(server: PluginServerInterface):
    plugins_dir = 'plugins'
    req_files = []
    if not os.path.exists(plugins_dir): return req_files
    base_depth = plugins_dir.count(os.sep)

    for root, dirs, files in os.walk(plugins_dir):
        current_depth = root.count(os.sep) - base_depth
        if current_depth >= config.max_scan_depth:
            dirs.clear() 
            continue
        dirs[:] = [d for d in dirs if not (d.startswith('.') or d == '__pycache__' or d.endswith('.disabled'))]
        if 'requirements.txt' in files:
            req_files.append(os.path.join(root, 'requirements.txt'))
    return req_files

def check_dependencies(source: CommandSource):
    """检查依赖并生成可点击的交互文本"""
    server = source.get_server()
    req_files = get_requirements_files(server)
    
    if not req_files:
        source.reply(PREFIX + '§a太棒了！所有启用的插件目录中都没有发现需要安装的依赖文件。')
        return

    source.reply('§m' + '-'*40)
    source.reply(PREFIX + f'§e扫描完成！发现 §c{len(req_files)}§e 个依赖配置文件:')
    for f in req_files:
        # 简化路径显示，去掉开头的 'plugins/' 让列表更清爽
        clean_name = f.replace('plugins' + os.sep, '')
        source.reply(f' §8> §7{clean_name}')
    
    # 制作交互式文本
    click_to_install = RText('§a[点击这里一键安全安装]§r').set_hover_text('§7点击将执行 !!pip install').set_click_event(RAction.run_command, '!!pip install')
    source.reply(RTextList(PREFIX, click_to_install))
    source.reply('§m' + '-'*40)

@new_thread('AutoPip_List')
def list_dependencies(source: CommandSource):
    """列出当前环境已安装的包"""
    source.reply(PREFIX + '§7正在获取已安装的依赖列表，请稍候...')
    try:
        result = subprocess.run([sys.executable, '-m', 'pip', 'list'], stdout=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
        source.reply('§m' + '-'*40)
        source.reply('§a当前 Python 环境已安装的包:')
        # 截取前 15 行防止刷屏，剩下的去控制台看
        lines = result.stdout.split('\n')
        for line in lines[:15]:
            if line.strip(): source.reply(f'§7{line}')
        if len(lines) > 15:
            source.reply('§8... 更多内容请在服务端后台控制台查看。')
            source.get_server().logger.info(f"\n{result.stdout}")
        source.reply('§m' + '-'*40)
    except Exception as e:
        source.reply(PREFIX + f'§c获取列表失败: {e}')

@new_thread('AutoPip_Install')
def install_dependencies(source: CommandSource):
    global is_installing
    server = source.get_server()
    
    with install_lock:
        if is_installing:
            source.reply(PREFIX + '§c安装任务正在后台进行中，请耐心等待，勿重复操作！')
            return
        is_installing = True

    try:
        req_files = get_requirements_files(server)
        if not req_files:
            source.reply(PREFIX + '§a没有找到需要安装的依赖文件。')
            return

        source.reply(PREFIX + '§e开始处理依赖，详细进度请查看 §b服务端后台控制台§e...')
        success_count, fail_count = 0, 0

        for req_file in req_files:
            server.logger.info(f"[{PLUGIN_METADATA['name']}] >> 开始处理: {req_file}")
            cmd = [sys.executable, '-m', 'pip', 'install', '-r', req_file]
            if config.pip_mirror: cmd.extend(['-i', config.pip_mirror])

            try:
                process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                    text=True, encoding='utf-8', errors='ignore'
                )
                for line in process.stdout:
                    clean_line = line.strip()
                    if clean_line: server.logger.info(f" [pip] {clean_line}")
                process.wait()

                if process.returncode == 0:
                    success_count += 1
                else:
                    fail_count += 1
                    server.logger.warning(f"[{PLUGIN_METADATA['name']}] << 失败 (Exit code {process.returncode}): {req_file}")
                    
            except Exception as e:
                fail_count += 1
                server.logger.error(f"系统异常: {e}")

        # 任务结果汇总
        source.reply('§m' + '-'*40)
        source.reply(PREFIX + '§a安装任务结束！')
        source.reply(f' §8> §a成功处理: {success_count} 个')
        source.reply(f' §8> §c失败处理: {fail_count} 个')
        
        if success_count > 0:
            click_reload = RText('§6[点击这里重载MCDR应用更改]§r').set_hover_text('§7执行 !!MCDR reload').set_click_event(RAction.run_command, '!!MCDR reload')
            source.reply(RTextList(PREFIX, click_reload))
        source.reply('§m' + '-'*40)

    finally:
        with install_lock:
            is_installing = False
