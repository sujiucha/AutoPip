import os
import sys
import re
import time
import zipfile
import subprocess
import threading
import urllib.request
import json
from mcdreforged.api.all import *

PLUGIN_METADATA = {
    'id': 'autopip',
    'version': '3.2.1',
    'name': 'Auto Pip Installer Pro',
    'description': '专业级 MCDR 插件依赖环境管家',
    'author': 'YourName',
    'link': 'https://github.com/sujiucha/AutoPip'
}

PREFIX = '§b[AutoPip]§r '
REPO_URL = "sujiucha/AutoPip"

class Configuration(Serializable):
    pip_mirror: str = "https://pypi.tuna.tsinghua.edu.cn/simple"
    max_scan_depth: int = 2

config: Configuration
is_installing = False
install_lock = threading.Lock()

def on_load(server: PluginServerInterface, prev):
    load_config(server)
    server.register_help_message('!!pip', 'AutoPip 专业依赖管家', permission=3)
    
    # 构建指令树
    command_tree = Literal('!!pip').requires(lambda src: src.has_permission(3)).runs(lambda src, ctx: show_help(src)).then(
        Literal('help').runs(lambda src, ctx: show_help(src))
    ).then(
        Literal('check').runs(lambda src, ctx: check_missing_dependencies(src))
    ).then(
        Literal('outdated').runs(lambda src, ctx: check_outdated(src))
    ).then(
        Literal('list').runs(lambda src, ctx: list_dependencies(src)).then(Text('query').runs(lambda src, ctx: list_dependencies(src, ctx['query'])))
    ).then(
        Literal('reload').runs(lambda src, ctx: reload_config_cmd(src))
    ).then(
        Literal('update').runs(lambda src, ctx: self_update_plugin(src))
    ).then(
        Literal('install').runs(lambda src, ctx: install_all_dependencies(src)).then(GreedyText('packages').runs(lambda src, ctx: manage_specific_packages(src, ctx['packages'], 'install')))
    ).then(
        Literal('uninstall').then(GreedyText('packages').runs(lambda src, ctx: manage_specific_packages(src, ctx['packages'], 'uninstall')))
    ).then(
        Literal('upgrade').then(GreedyText('packages').runs(lambda src, ctx: manage_specific_packages(src, ctx['packages'], 'upgrade')))
    )
    
    server.register_command(command_tree)
    server.logger.info(f'[{PLUGIN_METADATA["name"]}] V{PLUGIN_METADATA["version"]} 已加载！')
    
    # 启动后台守护任务
    boot_silent_scan(server)
    boot_check_update(server)

def show_help(source: CommandSource):
    help_msg = [
        '§m' + '-'*40,
        f'§bAuto Pip Installer Pro §7v{PLUGIN_METADATA["version"]}',
        '§m' + '-'*40,
        '§6!!pip check §f- 扫描所有插件缺失的依赖',
        '§6!!pip install §f- 一键自动安装所有缺失依赖',
        '§6!!pip install <包名> §f- 手动安装指定 Python 包',
        '§6!!pip uninstall <包名> §f- 手动强制卸载指定包',
        '§6!!pip list [搜索词] §f- 查看或搜索已安装的依赖',
        '§6!!pip outdated §f- 联网检查哪些依赖包可升级',
        '§6!!pip upgrade <包名> §f- 将指定的包升级到最新',
        '§6!!pip update §f- §a[热更新] §f一键升级本插件至最新版',
        '§6!!pip reload §f- 热重载插件配置文件',
        '§m' + '-'*40
    ]
    for line in help_msg: source.reply(line)

def load_config(server: PluginServerInterface):
    global config
    config = server.load_config_simple(target_class=Configuration)

def reload_config_cmd(source: CommandSource):
    load_config(source.get_server())
    source.reply(PREFIX + '§a配置文件已重新加载！')

# 扫描普通目录及压缩包内的依赖配置文件
def get_requirements_files(server: PluginServerInterface):
    plugins_dir = 'plugins'
    req_files = []
    packed_pkgs = []
    if not os.path.exists(plugins_dir): return req_files, packed_pkgs
    base_depth = plugins_dir.count(os.sep)
    for root, dirs, files in os.walk(plugins_dir):
        if root.count(os.sep) - base_depth >= config.max_scan_depth:
            dirs.clear(); continue
        dirs[:] = [d for d in dirs if not (d.startswith('.') or d == '__pycache__' or d.endswith('.disabled'))]
        if 'requirements.txt' in files:
            req_files.append(os.path.join(root, 'requirements.txt'))
        for file in files:
            if file.endswith('.mcdr') or file.endswith('.pyz'):
                try:
                    with zipfile.ZipFile(os.path.join(root, file), 'r') as z:
                        if 'requirements.txt' in z.namelist():
                            content = z.read('requirements.txt').decode('utf-8', errors='ignore')
                            for line in content.split('\n'):
                                line = line.strip()
                                if line and not line.startswith('#'):
                                    if line: packed_pkgs.append(line)
                except Exception: pass
    return req_files, list(set(packed_pkgs))

# 比对当前环境，筛选出未安装的依赖
def get_missing_packages(req_files, packed_pkgs):
    result = subprocess.run([sys.executable, '-m', 'pip', 'list'], stdout=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
    installed_packages = result.stdout.lower()
    missing_pkgs = []
    for req_file in req_files:
        with open(req_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'): continue
                pkg_name = re.split(r'[=><~]', line)[0].strip().lower()
                if pkg_name and pkg_name not in installed_packages:
                    missing_pkgs.append(line)
    for raw_pkg in packed_pkgs:
        pkg_name = re.split(r'[=><~]', raw_pkg)[0].strip().lower()
        if pkg_name and pkg_name not in installed_packages:
            missing_pkgs.append(raw_pkg)
    return list(set(missing_pkgs))

# 版本号对比校验
def is_version_greater(latest: str, current: str) -> bool:
    try:
        l_parts = [int(i) for i in latest.split('.')]
        c_parts = [int(i) for i in current.split('.')]
        return l_parts > c_parts
    except Exception:
        return latest != current

@new_thread('AutoPip_BootScan')
def boot_silent_scan(server: PluginServerInterface):
    req_files, packed_pkgs = get_requirements_files(server)
    if not req_files and not packed_pkgs: return
    try:
        missing_pkgs = get_missing_packages(req_files, packed_pkgs)
        if missing_pkgs:
            time.sleep(6)
            clean_names = [re.split(r'[=><~]', p)[0].strip() for p in missing_pkgs]
            server.logger.warning(f"[{PLUGIN_METADATA['name']}] 警告！检测到有插件缺失 Python 依赖: {', '.join(clean_names)}")
            server.logger.warning(f"[{PLUGIN_METADATA['name']}] 请在控制台输入 !!pip check 或 !!pip install 进行一键修补！")
    except Exception: pass

@new_thread('AutoPip_BootUpdateCheck')
def boot_check_update(server: PluginServerInterface):
    time.sleep(8)
    try:
        api_url = f"https://api.github.com/repos/{REPO_URL}/releases/latest"
        req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            latest_version = data['tag_name'].replace('v', '').replace('V', '')
            current_version = PLUGIN_METADATA['version']
            
            if is_version_greater(latest_version, current_version):
                server.logger.info(f"[{PLUGIN_METADATA['name']}] ==============================================")
                server.logger.info(f"[{PLUGIN_METADATA['name']}] 发现新版本 AutoPip: v{latest_version} (当前 v{current_version})")
                server.logger.info(f"[{PLUGIN_METADATA['name']}] 请在游戏内或控制台输入 !!pip update 进行一键热更新！")
                server.logger.info(f"[{PLUGIN_METADATA['name']}] ==============================================")
    except Exception: pass

@new_thread('AutoPip_SelfUpdate')
def self_update_plugin(source: CommandSource):
    server = source.get_server()
    source.reply(PREFIX + '§7正在连接 GitHub 检查新版本...')
    try:
        api_url = f"https://api.github.com/repos/{REPO_URL}/releases/latest"
        req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            
        latest_version = data['tag_name'].replace('v', '').replace('V', '')
        current_version = PLUGIN_METADATA['version']
        
        if is_version_greater(latest_version, current_version):
            source.reply(PREFIX + f'§a发现新版本 §ev{latest_version}§a，正在自动下载覆盖...')
            download_url = f"https://mirror.ghproxy.com/https://raw.githubusercontent.com/{REPO_URL}/main/AutoPip.py"
            dl_req = urllib.request.Request(download_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(dl_req, timeout=15) as dl_response:
                new_code = dl_response.read().decode('utf-8')
            plugin_path = os.path.abspath(__file__)
            with open(plugin_path, 'w', encoding='utf-8') as f:
                f.write(new_code)
            source.reply(PREFIX + '§a更新包下载并覆盖完成！正在重启自身...')
            server.execute('!!MCDR plugin reload autopip')
        else:
            source.reply(PREFIX + '§a当前已是最新版本，无需更新！')
    except Exception as e:
        source.reply(PREFIX + f'§c热更新失败，请检查网络: {e}')

@new_thread('AutoPip_Manage')
def manage_specific_packages(source: CommandSource, packages_str: str, action: str):
    global is_installing
    server = source.get_server()
    packages = packages_str.split()
    with install_lock:
        if is_installing:
            source.reply(PREFIX + '§c后台有 pip 任务正在运行，请稍后再试！')
            return
        is_installing = True
    source.reply(PREFIX + f'§e正在执行 {action}: §b{", ".join(packages)} §e请查看控制台进度...')
    try:
        if action == 'install': cmd = [sys.executable, '-m', 'pip', 'install'] + packages
        elif action == 'upgrade': cmd = [sys.executable, '-m', 'pip', 'install', '--upgrade'] + packages
        elif action == 'uninstall': cmd = [sys.executable, '-m', 'pip', 'uninstall', '-y'] + packages
        if action != 'uninstall' and config.pip_mirror: cmd.extend(['-i', config.pip_mirror])
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='ignore')
        for line in process.stdout:
            if line.strip(): server.logger.info(f" [pip] {line.strip()}")
        process.wait()
        if process.returncode == 0: source.reply(PREFIX + f'§a操作成功！已完成 {action}。')
        else: source.reply(PREFIX + f'§c操作失败！请检查控制台报错。')
    finally:
        with install_lock: is_installing = False

@new_thread('AutoPip_Outdated')
def check_outdated(source: CommandSource):
    source.reply(PREFIX + '§7正在联网比对包版本，请稍候...')
    try:
        cmd = [sys.executable, '-m', 'pip', 'list', '--outdated']
        if config.pip_mirror: cmd.extend(['-i', config.pip_mirror])
        result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
        lines = result.stdout.split('\n')[2:]
        outdated_pkgs = [line for line in lines if line.strip()]
        if not outdated_pkgs:
            source.reply(PREFIX + '§a当前环境的所有依赖均是最新版本！')
            return
        source.reply('§m' + '-'*40)
        source.reply(PREFIX + f'§e发现 {len(outdated_pkgs)} 个可升级的包:')
        for line in outdated_pkgs[:10]: source.reply(f'§7 {line}')
        if len(outdated_pkgs) > 10: source.reply('§8... 剩余内容请查看控制台。')
        source.reply('§6输入 §c!!pip upgrade <包名> §6来进行升级。')
        source.reply('§m' + '-'*40)
    except Exception as e:
        source.reply(PREFIX + f'§c检查更新失败: {e}')

@new_thread('AutoPip_CheckMissing')
def check_missing_dependencies(source: CommandSource):
    source.reply(PREFIX + '§7正在扫描插件目录并核对当前环境，请稍候...')
    server = source.get_server()
    is_console = source.is_console
    req_files, packed_pkgs = get_requirements_files(server)
    if not req_files and not packed_pkgs:
        source.reply(PREFIX + '§a没有发现任何依赖要求。')
        return
        
    try:
        missing_pkgs = get_missing_packages(req_files, packed_pkgs)
        source.reply('§m' + '-'*40)
        if not missing_pkgs:
            source.reply(PREFIX + '§a太棒了！所有启用的插件依赖均已满足，环境非常健康！')
        else:
            clean_names = [re.split(r'[=><~]', p)[0].strip() for p in missing_pkgs]
            source.reply(PREFIX + f'§c警告！发现 §e{len(clean_names)}§c 个缺失的依赖包:')
            source.reply(f' §8> §7{", ".join(clean_names)}')
            
            # 兼容游戏内点击输入指令
            if is_console:
                source.reply(PREFIX + '§e请输入 §c!!pip install §e进行一键自动安装')
            else:
                click_to_install = RText('§a[点击获取一键自动安装指令]§r').set_hover_text('§7点我自动把指令填入聊天框').set_click_event(RAction.suggest_command, '!!pip install')
                source.reply(RTextList(PREFIX, click_to_install))
        source.reply('§m' + '-'*40)
    except Exception as e:
        source.reply(PREFIX + f'§c核对环境时发生错误: {e}')

@new_thread('AutoPip_List')
def list_dependencies(source: CommandSource, query: str = None):
    server = source.get_server()
    is_console = source.is_console
    if not is_console: source.reply(PREFIX + '§7正在获取依赖列表...')
    else: server.logger.info(f"[{PLUGIN_METADATA['name']}] 正在获取完整依赖列表...")
    try:
        result = subprocess.run([sys.executable, '-m', 'pip', 'list'], stdout=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
        lines = result.stdout.split('\n')
        header = lines[:2]
        body = [line for line in lines[2:] if line.strip()]
        if query:
            query = query.lower()
            filtered_body = [line for line in body if query in line.lower()]
            if is_console:
                server.logger.info(f"\n=================== 搜索 '{query}' 的结果 ({len(filtered_body)} 个) ===================\n" + "\n".join(header + filtered_body))
            else:
                source.reply('§m' + '-'*40)
                source.reply(PREFIX + f'§e搜索 §b"{query}"§e 的结果 ({len(filtered_body)} 个):')
                if filtered_body:
                    source.reply(f'§a{header[0]}\n§a{header[1]}')
                    for line in filtered_body[:15]: source.reply(f'§7{line}')
                    if len(filtered_body) > 15: source.reply(f'§8... 已省略其余 {len(filtered_body)-15} 个结果。')
                else: source.reply('§c没有找到任何匹配的包。')
                source.reply('§m' + '-'*40)
        else:
            if is_console:
                server.logger.info(f"\n=================== 完整 Python 依赖包列表 ===================\n{result.stdout}\n==============================================================")
            else:
                source.reply('§m' + '-'*40)
                source.reply(PREFIX + '§a当前已安装的包 (仅展示前15行):')
                for line in lines[:17]:
                    if line.strip(): source.reply(f'§7{line}')
                click_to_print_all = RText('§e[点击获取输出控制台指令]§r').set_hover_text('§7点我自动把指令填入聊天框').set_click_event(RAction.suggest_command, '!!pip list --show-all-internal')
                source.reply(RTextList(PREFIX, click_to_print_all))
                source.reply('§m' + '-'*40)
    except Exception as e:
        if is_console: server.logger.error(f"获取列表失败: {e}")
        else: source.reply(PREFIX + f'§c获取列表失败: {e}')

@new_thread('AutoPip_PrintAll')
def print_all_internal(server: PluginServerInterface):
    try:
        result = subprocess.run([sys.executable, '-m', 'pip', 'list'], stdout=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
        server.logger.info(f"\n=================== 完整 Python 依赖包列表 ===================\n{result.stdout}\n==============================================================")
    except Exception: pass

def on_user_info(server: PluginServerInterface, info):
    if info.is_user and info.content == '!!pip list --show-all-internal':
        if server.get_plugin_command_source(info).has_permission(3):
            print_all_internal(server)

# 异步执行一键安装
@new_thread('AutoPip_InstallAll')
def install_all_dependencies(source: CommandSource):
    global is_installing
    server = source.get_server()
    with install_lock:
        if is_installing:
            source.reply(PREFIX + '§c安装任务正在进行中！')
            return
        is_installing = True
    try:
        req_files, packed_pkgs = get_requirements_files(server)
        if not req_files and not packed_pkgs:
            source.reply(PREFIX + '§a没有发现任何依赖要求。')
            return
            
        missing_pkgs = get_missing_packages(req_files, packed_pkgs)
        if not missing_pkgs:
            source.reply(PREFIX + '§a所有依赖均已满足，无需重复安装！')
            return
            
        source.reply(PREFIX + f'§e开始集中安装 {len(missing_pkgs)} 个缺失依赖，详见控制台...')
        cmd = [sys.executable, '-m', 'pip', 'install'] + missing_pkgs
        if config.pip_mirror: cmd.extend(['-i', config.pip_mirror])
        
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='ignore')
            for line in process.stdout:
                if line.strip(): server.logger.info(f" [pip] {line.strip()}")
            process.wait()
            
            if process.returncode == 0:
                source.reply(PREFIX + '§a所有缺失依赖安装完毕！')
            else:
                source.reply(PREFIX + '§c部分依赖安装失败，请检查控制台红字报错！')
        except Exception as e:
            server.logger.error(f"执行安装时发生错误: {e}")
            
    finally:
        with install_lock: is_installing = False
