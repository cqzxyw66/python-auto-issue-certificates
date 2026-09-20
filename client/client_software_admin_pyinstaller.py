#! /usr/bin/python3
# -*- coding: utf-8 -*-
"""
客户端打包工具（公司管理员使用）

为什么需要这个工具
------------------
`client/client_software_pyinstaller_new.py` 只能在 Windows 上运行，
而线上部署环境（Linux/Docker）无法交叉编译出 Windows 的 exe。
因此把「在 Windows 上打包客户端」这一步交给公司管理员：

    1. 开发者在本机预先打包出本工具的 exe 并分发给管理员；
    2. 管理员运行本工具，填写自己部署的项目访问地址；
    3. 本工具自动从服务端下载打包所需的源码（client_exe.py 等）；
    4. 本工具自动检查并配置本机 Python 环境（Python / pip / PyInstaller 等）；
    5. 本工具在本机执行打包，生成 {通用名称}_certificate_tool.exe；
    6. 生成后自动上传到管理员自己部署的环境（也可取消勾选后手动上传）。

开发者打包本工具的命令（在项目根目录执行）：

    pyinstaller -F -w --clean --name=certificate_builder ^
        -i config/logo.ico client/client_software_admin_pyinstaller.py

打包完成后建议把生成的 dist/certificate_builder.exe 放到服务器 config 目录，
管理员即可在“软件管理”页面直接下载它。

注意：如果额外指定了 --specpath，PyInstaller 会把 -i 的相对路径按 spec 目录
解析（例如 --specpath=build_tmp 时 config/logo.ico 会被解析成
build_tmp/config/logo.ico 并报 FileNotFoundError），此时 -i 必须写绝对路径。

服务端需要提供以下两个接口（见 app.py）：
    GET  /client_source_package  下载打包源码 zip
    POST /upload_client_exe      上传打包结果 exe
"""

import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
import zipfile

import requests
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

# ---------------------------------------------------------------- 常量配置

DEFAULT_SERVER_URL = 'http://localhost:5000'
COMPANY_API = '/company_query'                 # 企业信息接口
SOURCE_PACKAGE_API = '/client_source_package'  # 打包源码 zip 下载接口
UPLOAD_API = '/upload_client_exe'              # 打包结果 exe 上传接口
UPLOAD_TOKEN_FIELD = 'token'                   # 上传口令字段名（服务端配置了 CLIENT_UPLOAD_TOKEN 时才需要）

BUILD_SCRIPT_NAME = 'client_software_pyinstaller_new.py'
REQUIRED_SOURCE_FILES = (
    BUILD_SCRIPT_NAME,
    'client_exe.py',
    'get_computer_info.py',
    'create_certificate.py',
    'logo.ico',
)
BUILD_PACKAGES = ('pyinstaller', 'pyinstaller-versionfile', 'requests', 'cryptography')
DEFAULT_PIP_INDEX = 'https://pypi.tuna.tsinghua.edu.cn/simple'
MIN_PYTHON_VERSION = (3, 8)
BUILD_TIMEOUT = 1800  # 打包超时时间（秒）
CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class BuilderError(Exception):
    """业务异常：消息会直接展示给管理员，不需要打印堆栈。"""


# ---------------------------------------------------------------- 通用函数

def default_output_dir():
    """默认输出目录：桌面（存在时），否则用户主目录。"""
    desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
    return desktop if os.path.isdir(desktop) else os.path.expanduser('~')


def normalize_base_url(raw_url):
    """把管理员填写的地址规范成 http(s)://host:port 形式。"""
    url = (raw_url or '').strip()
    if not url:
        raise BuilderError('请先填写项目访问地址，例如：http://192.168.1.10:5000')
    if not re.match(r'^https?://', url, re.IGNORECASE):
        url = 'http://' + url
    return url.rstrip('/')


def enable_dpi_awareness():
    """Windows 高分屏下让界面更清晰。"""
    if os.name != 'nt':
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


# ---------------------------------------------------------------- 主界面

class CertificateBuilderApp:
    def __init__(self, root):
        self.root = root
        self.log_queue = queue.Queue()
        self.callback_queue = queue.Queue()
        self.working = False
        self._build_ui()
        self.root.after(100, self._poll_ui)

    # ------------------------------------------------------------ 界面构建

    def _build_ui(self):
        self.root.title('客户端打包工具')
        window_width, window_height = 820, 620
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        self.root.geometry(
            f'{window_width}x{window_height}+{int((screen_width - window_width) / 2)}+{int((screen_height - window_height) / 2)}'
        )
        self.root.minsize(720, 520)

        font_label = ('Microsoft YaHei', 10, 'bold')
        font_text = ('Microsoft YaHei', 10)
        container = tk.Frame(self.root, padx=12, pady=10)
        container.pack(fill='both', expand=True)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(6, weight=1)

        # 项目访问地址
        tk.Label(container, text='项目访问地址：', font=font_label).grid(row=0, column=0, sticky='w', pady=3)
        self.url_var = tk.StringVar(value=DEFAULT_SERVER_URL)
        tk.Entry(container, textvariable=self.url_var, font=font_text).grid(
            row=0, column=1, columnspan=2, sticky='we', padx=(0, 8), pady=3)
        tk.Button(container, text='测试连接', width=10, command=self.on_test_connection).grid(row=0, column=3, pady=3)

        # 输出目录
        tk.Label(container, text='输出目录：', font=font_label).grid(row=1, column=0, sticky='w', pady=3)
        self.output_var = tk.StringVar(value=default_output_dir())
        tk.Entry(container, textvariable=self.output_var, font=font_text).grid(
            row=1, column=1, columnspan=2, sticky='we', padx=(0, 8), pady=3)
        tk.Button(container, text='浏览...', width=10, command=self.on_browse_output).grid(row=1, column=3, pady=3)

        # pip 软件源
        tk.Label(container, text='pip 软件源：', font=font_label).grid(row=2, column=0, sticky='w', pady=3)
        self.index_var = tk.StringVar(value=DEFAULT_PIP_INDEX)
        tk.Entry(container, textvariable=self.index_var, font=font_text).grid(
            row=2, column=1, columnspan=2, sticky='we', padx=(0, 8), pady=3)
        tk.Button(container, text='官方源', width=10,
                  command=lambda: self.index_var.set('')).grid(row=2, column=3, pady=3)

        # 上传口令（服务端设置 CLIENT_UPLOAD_TOKEN 时才需要填写）
        tk.Label(container, text='上传口令：', font=font_label).grid(row=3, column=0, sticky='w', pady=3)
        self.token_var = tk.StringVar()
        tk.Entry(container, textvariable=self.token_var, font=font_text, show='*').grid(
            row=3, column=1, columnspan=3, sticky='we', padx=(0, 8), pady=3)

        # 选项
        options = tk.Frame(container)
        options.grid(row=4, column=0, columnspan=4, sticky='we', pady=(6, 2))
        self.upload_var = tk.BooleanVar(value=True)
        tk.Checkbutton(options, text='生成后自动上传到服务器', variable=self.upload_var,
                       font=font_text).pack(side='left')
        self.skip_install_var = tk.BooleanVar(value=False)
        tk.Checkbutton(options, text='跳过依赖安装（本机环境已就绪时勾选）', variable=self.skip_install_var,
                       font=font_text).pack(side='left', padx=(16, 0))
        self.insecure_var = tk.BooleanVar(value=False)
        tk.Checkbutton(options, text='忽略 HTTPS 证书校验', variable=self.insecure_var,
                       font=font_text).pack(side='left', padx=(16, 0))

        # 运行日志
        tk.Label(container, text='运行日志：', font=font_label).grid(row=5, column=0, columnspan=4, sticky='w', pady=(8, 0))
        self.log_text = scrolledtext.ScrolledText(container, height=18, font=('Consolas', 9),
                                                  state='disabled', wrap='word')
        self.log_text.grid(row=6, column=0, columnspan=4, sticky='nsew', pady=(4, 8))

        # 底部按钮
        bottom = tk.Frame(container)
        bottom.grid(row=7, column=0, columnspan=4, sticky='we')
        self.start_button = tk.Button(bottom, text='开始生成客户端', font=('Microsoft YaHei', 12, 'bold'),
                                      width=18, command=self.on_start)
        self.start_button.pack(side='left')
        tk.Button(bottom, text='打开输出目录', width=14,
                  command=self.on_open_output).pack(side='left', padx=8)
        tk.Button(bottom, text='清空日志', width=10, command=self.clear_log).pack(side='left')
        self.progress = ttk.Progressbar(bottom, mode='indeterminate', length=160)
        self.progress.pack(side='right')

        self.status_var = tk.StringVar(value='就绪')
        tk.Label(container, textvariable=self.status_var, font=font_text, anchor='w', fg='#444444').grid(
            row=8, column=0, columnspan=4, sticky='we', pady=(4, 0))

    # ------------------------------------------------------------ 线程安全辅助

    def post(self, func):
        """把需要在主线程执行的回调排入队列（工作线程中调用是安全的）。"""
        self.callback_queue.put(func)

    def log(self, message='', level='info'):
        prefix = {'info': '', 'ok': '✅ ', 'warn': '⚠️ ', 'error': '❌ '}.get(level, '')
        stamp = time.strftime('%H:%M:%S')
        for line in str(message).splitlines() or ['']:
            self.log_queue.put(f'[{stamp}] {prefix}{line}')

    def _poll_ui(self):
        while True:
            try:
                callback = self.callback_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except Exception:
                pass
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.configure(state='normal')
            self.log_text.insert('end', line + '\n')
            self.log_text.see('end')
            self.log_text.configure(state='disabled')
        self.root.after(100, self._poll_ui)

    def _ask_yes_no(self, title, question):
        """在主线程弹出询问框并等待结果。"""
        answer = {}
        done = threading.Event()

        def show():
            try:
                answer['value'] = messagebox.askyesno(title, question)
            finally:
                done.set()

        self.post(show)
        done.wait()
        return answer.get('value', False)

    def clear_log(self):
        self.log_text.configure(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.configure(state='disabled')

    # ------------------------------------------------------------ 按钮事件

    def on_browse_output(self):
        selected = filedialog.askdirectory(title='选择打包结果的保存目录',
                                           initialdir=self.output_var.get() or default_output_dir())
        if selected:
            self.output_var.set(os.path.normpath(selected))

    def on_open_output(self):
        path = (self.output_var.get() or '').strip() or default_output_dir()
        if not os.path.isdir(path):
            messagebox.showwarning('提示', '输出目录还不存在。')
            return
        if hasattr(os, 'startfile'):
            os.startfile(path)
        else:
            webbrowser.open('file://' + path)

    def on_test_connection(self):
        if self.working:
            return
        try:
            base_url = normalize_base_url(self.url_var.get())
        except BuilderError as exc:
            messagebox.showwarning('提示', str(exc))
            return
        self.log(f'测试连接：{base_url} ...')
        threading.Thread(target=self._test_connection, args=(base_url,), daemon=True).start()

    def _test_connection(self, base_url):
        try:
            self._fetch_company_info(base_url)
            self.log('服务连接正常。', 'ok')
            self.post(lambda: self.status_var.set('服务连接正常'))
        except BuilderError as exc:
            self.log(str(exc), 'error')
            self.post(lambda: self.status_var.set('连接失败'))

    def on_start(self):
        if self.working:
            return
        try:
            base_url = normalize_base_url(self.url_var.get())
        except BuilderError as exc:
            messagebox.showwarning('提示', str(exc))
            return

        output_dir = (self.output_var.get() or '').strip()
        if not output_dir:
            messagebox.showwarning('提示', '请选择打包结果的保存目录。')
            return
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as exc:
            messagebox.showerror('提示', f'输出目录不可用：{exc}')
            return

        self.working = True
        self.start_button.config(state='disabled')
        self.progress.start(12)
        self.status_var.set('正在生成客户端，请勿关闭窗口...')
        self.log('=' * 70, 'info')
        self.log(f'开始打包客户端，项目地址：{base_url}')
        threading.Thread(target=self._run_pipeline, args=(base_url, output_dir), daemon=True).start()

    # ------------------------------------------------------------ 主流程

    def _run_pipeline(self, base_url, output_dir):
        work_dir = None
        ok = False
        message = '打包流程异常结束。'
        uploaded_name = None
        try:
            # 1. 连通性检查 + 获取企业信息
            company = self._fetch_company_info(base_url)

            # 2. 下载打包源码
            work_dir = tempfile.mkdtemp(prefix='certificate_build_')
            self.log(f'创建临时工作目录：{work_dir}')
            self._download_sources(base_url, work_dir)

            # 3. 配置本机 Python 环境（依赖装在临时虚拟环境里，不污染全局）
            python_cmd = self._ensure_python()
            if self.skip_install_var.get():
                self.log('已勾选“跳过依赖安装”，直接使用本机现有依赖。', 'warn')
                build_python = python_cmd
            else:
                build_python = self._install_packages(python_cmd, work_dir)

            # 4. 执行打包
            # 必须用虚拟环境的解释器，否则用全局 python 跑打包脚本会找不到刚装好的 PyInstaller
            exe_name, exe_path = self._run_build(build_python, work_dir, base_url, company)

            # 5. 复制到输出目录
            target_path = os.path.join(output_dir, exe_name)
            shutil.copy2(exe_path, target_path)
            self.log(f'打包结果已保存：{target_path}', 'ok')

            # 6. 上传到管理员自己部署的环境
            if self.upload_var.get():
                uploaded_name = self._upload(base_url, target_path)
            else:
                self.log('已跳过自动上传，请手动把 exe 上传到你的服务器。', 'warn')

            ok = True
            message = f'客户端已生成：\n{target_path}\n\n'
            if uploaded_name:
                message += f'已上传到服务器：{uploaded_name}'
            else:
                message += '未上传到服务器，请手动上传。'
        except BuilderError as exc:
            message = str(exc)
            self.log(message, 'error')
        except Exception as exc:  # 兜底，避免线程静默退出
            self.log(traceback.format_exc(), 'error')
            message = f'出现未预期的错误：{exc}'
        finally:
            if work_dir and os.path.isdir(work_dir):
                shutil.rmtree(work_dir, ignore_errors=True)
                self.log(f'已清理临时工作目录（含临时虚拟环境）：{work_dir}')

        self._finish(ok, message)

    def _finish(self, ok, message):
        def update():
            self.working = False
            self.progress.stop()
            self.start_button.config(state='normal')
            self.status_var.set('生成完成' if ok else '生成失败')
            self.log('=' * 70)
            if ok:
                self.log('客户端打包完成。', 'ok')
                messagebox.showinfo('完成', message)
            else:
                self.log(message, 'error')
                messagebox.showerror('失败', message)

        self.post(update)

    # ------------------------------------------------------------ 各步骤实现

    def _verify_tls(self):
        """是否校验 HTTPS 证书。"""
        return not self.insecure_var.get()

    def _fetch_company_info(self, base_url):
        url = base_url + COMPANY_API
        self.log(f'获取企业信息：{url}')
        try:
            response = requests.get(url, timeout=20, verify=self._verify_tls())
        except requests.RequestException as exc:
            raise BuilderError(f'无法连接项目地址：{exc}\n请确认服务已启动、地址和端口填写正确。')
        if response.status_code != 200:
            raise BuilderError(f'获取企业信息失败，服务端返回状态码 {response.status_code}，请确认地址是否正确。')
        try:
            data = response.json()
        except ValueError:
            raise BuilderError('服务端返回的数据不是合法的 JSON，请确认填写的是本项目服务地址。')
        self.log(
            f"企业名称：{data.get('company_name')}；通用名称：{data.get('common_name')}；服务地址：{data.get('url')}", 'ok')
        return data

    def _download_sources(self, base_url, work_dir):
        url = base_url + SOURCE_PACKAGE_API
        self.log(f'下载打包源码：{url}')
        try:
            response = requests.get(url, timeout=60, stream=True, verify=self._verify_tls())
        except requests.RequestException as exc:
            raise BuilderError(f'下载打包源码失败：{exc}')
        if response.status_code == 404:
            raise BuilderError('服务端没有 /client_source_package 接口，请先把最新版 app.py 部署到服务器后再试。')
        if response.status_code != 200:
            raise BuilderError(f'下载打包源码失败，服务端返回状态码 {response.status_code}。')

        zip_path = os.path.join(work_dir, 'client_build_sources.zip')
        with open(zip_path, 'wb') as f:
            for chunk in response.iter_content(64 * 1024):
                if chunk:
                    f.write(chunk)
        try:
            with zipfile.ZipFile(zip_path) as bundle:
                bundle.extractall(work_dir)
        except zipfile.BadZipFile:
            raise BuilderError('下载到的源码包已损坏，请重试。')
        finally:
            if os.path.exists(zip_path):
                os.remove(zip_path)

        missing = [name for name in REQUIRED_SOURCE_FILES if not os.path.exists(os.path.join(work_dir, name))]
        if missing:
            raise BuilderError('源码包缺少必要文件：' + '、'.join(missing) + '，请检查服务端 client 目录是否完整。')

        # client_software_pyinstaller_new.py 需要 config 目录存在，并在打包结束后清空其中内容
        os.makedirs(os.path.join(work_dir, 'config'), exist_ok=True)
        self.log('源码下载完成：' + '、'.join(REQUIRED_SOURCE_FILES), 'ok')

    def _child_env(self):
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'
        # 避免 PyInstaller 打包后的环境变量干扰子进程解释器
        env.pop('PYTHONHOME', None)
        env.pop('PYTHONPATH', None)
        # 本工具自身若在某个虚拟环境里运行，不要把该状态带给子进程，
        # 否则子进程里 pip / python 的解析结果会被意外改写
        env.pop('VIRTUAL_ENV', None)
        return env

    def _probe(self, cmd):
        """静默执行一条探测命令，成功返回标准输出，失败返回 None。"""
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                                    errors='replace', timeout=30, env=self._child_env(),
                                    creationflags=CREATE_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        return ((result.stdout or '') + (result.stderr or '')).strip()

    def _run_command(self, cmd, cwd=None, timeout=None):
        """执行外部命令，并把输出实时写入日志。"""
        self.log('$ ' + ' '.join(str(part) for part in cmd))
        try:
            process = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding='utf-8', errors='replace', bufsize=1,
                                       env=self._child_env(), creationflags=CREATE_NO_WINDOW)
        except OSError as exc:
            raise BuilderError(f'无法执行命令 {cmd[0]}：{exc}')

        timed_out = []
        killer = None
        if timeout:
            def kill_process():
                timed_out.append(True)
                process.kill()

            killer = threading.Timer(timeout, kill_process)
            killer.start()
        try:
            stdout = process.stdout
            if stdout is None:
                raise BuilderError('无法读取命令输出：' + ' '.join(str(part) for part in cmd))
            for line in stdout:
                line = line.rstrip()
                if line:
                    self.log('    ' + line)
            process.wait()
        finally:
            if killer:
                killer.cancel()
        if timed_out:
            raise BuilderError(f'命令执行超时（超过 {timeout} 秒）：{" ".join(str(part) for part in cmd)}')
        return process.returncode

    def _find_python(self):
        if os.name == 'nt':
            candidates = [['py', '-3'], ['python'], ['python3']]
        else:
            candidates = [['python3'], ['python']]
        for cmd in candidates:
            version_text = self._probe(cmd + ['-c', 'import sys;print("%d.%d.%d" % sys.version_info[:3])'])
            if not version_text:
                continue
            last_line = version_text.splitlines()[-1].strip()
            if not re.match(r'^\d+\.\d+\.\d+$', last_line):
                continue
            version = tuple(int(part) for part in last_line.split('.'))
            if version < MIN_PYTHON_VERSION:
                self.log(f'检测到 {" ".join(cmd)} 对应的 Python {last_line} 版本过低，跳过。', 'warn')
                continue
            if self._probe(cmd + ['-c', 'import tkinter']) is None:
                self.log(f'{" ".join(cmd)} 缺少 tkinter 模块（常见于应用商店版 Python），跳过。', 'warn')
                continue
            self.log(f'已检测到 Python {last_line}（命令：{" ".join(cmd)}）', 'ok')
            return cmd
        return None

    def _ensure_python(self):
        python_cmd = self._find_python()
        if python_cmd:
            return python_cmd

        if os.name != 'nt':
            raise BuilderError('未检测到可用的 Python 3，请先安装 Python 3.8 或更高版本后重试。')

        if not self._ask_yes_no(
            '缺少 Python 环境',
            '未检测到可用的 Python 3 环境。\n\n是否尝试用 winget 自动安装 Python 3.12（当前用户，无需管理员权限）？\n\n'
            '选择“否”将打开 Python 官网，由你手动下载安装。'
        ):
            webbrowser.open('https://www.python.org/downloads/windows/')
            raise BuilderError('已为你打开 Python 下载页面，请安装后重试（安装时请勾选 Add python.exe to PATH）。')

        self.log('尝试通过 winget 自动安装 Python 3.12 ...')
        try:
            code = self._run_command([
                'winget', 'install', '-e', '--id', 'Python.Python.3.12', '--scope', 'user',
                '--accept-package-agreements', '--accept-source-agreements', '--disable-interactivity',
            ], timeout=1800)
        except BuilderError:
            code = -1
        if code != 0:
            webbrowser.open('https://www.python.org/downloads/windows/')
            raise BuilderError('自动安装 Python 失败，已为你打开下载页面，请手动安装后重试。')

        python_cmd = self._find_python()
        if not python_cmd:
            raise BuilderError('Python 已安装但当前进程还找不到它，请重新打开本工具再试。')
        return python_cmd

    def _venv_python(self, venv_dir):
        """返回虚拟环境解释器的绝对路径。"""
        if os.name == 'nt':
            return os.path.join(venv_dir, 'Scripts', 'python.exe')
        return os.path.join(venv_dir, 'bin', 'python')

    def _install_packages(self, python_cmd, work_dir):
        """在 work_dir 下建一个临时虚拟环境并安装打包依赖，返回该环境的命令前缀（列表）。

        返回值与 _find_python / _ensure_python 保持一致，都是“命令前缀列表”，
        调用方可以直接做 venv_cmd + [参数...]，不要再返回裸路径字符串。

        这里刻意不调用 Activate.ps1 / deactivate：_run_command 每次都新起一个进程，
        激活只对那一个进程有效，进程一结束就失效，下一个进程仍然用全局 python，
        依赖就会装到全局去。正确做法是直接用虚拟环境里的 python 绝对路径执行 pip，
        这样既不污染全局，也不依赖执行策略是否允许运行 .ps1 脚本。
        """

        venv_dir = os.path.join(work_dir, '.venv')
        venv_python = self._venv_python(venv_dir)
        self.log(f'创建临时虚拟环境（打包结束后随工作目录一起删除）：{venv_dir}')
        if self._run_command(python_cmd + ['-m', 'venv', venv_dir], timeout=600) != 0:
            raise BuilderError('创建虚拟环境失败，请确认 Python 安装完整（自带 venv 与 pip 模块）。')
        if not os.path.exists(venv_python):
            raise BuilderError(f'虚拟环境创建异常，未找到解释器：{venv_python}')

        venv_cmd = [venv_python]

        cmd = venv_cmd + ['-m', 'pip', 'install', '--upgrade', '--disable-pip-version-check',
                          '--no-warn-script-location', *BUILD_PACKAGES]
        index = (self.index_var.get() or '').strip()
        if index:
            cmd += ['-i', index]

        self.log('安装打包所需依赖（pyinstaller / pyinstaller-versionfile / requests / cryptography）...')

        if self._run_command(cmd, timeout=1800) != 0:
            raise BuilderError('依赖安装失败，请检查网络，或更换 pip 软件源后重试。')
        self.log('依赖安装完成。', 'ok')
        return venv_cmd

    def _run_build(self, python_cmd, work_dir, base_url, company):
        script_path = os.path.join(work_dir, BUILD_SCRIPT_NAME)
        query_url = base_url + COMPANY_API
        self.log(f'开始打包（首次打包通常需要 1-3 分钟）：{" ".join(python_cmd)} {BUILD_SCRIPT_NAME} {query_url}')
        code = self._run_command(python_cmd + [script_path, query_url], cwd=work_dir, timeout=BUILD_TIMEOUT)
        if code != 0:
            raise BuilderError('打包脚本执行失败，请查看上方日志定位原因。')

        common_name = str((company or {}).get('common_name') or '').strip()
        candidates = []
        if common_name:
            candidates.append(f'{common_name}_certificate_tool.exe')
        candidates += sorted(item for item in os.listdir(work_dir) if item.lower().endswith('.exe'))
        for name in candidates:
            path = os.path.join(work_dir, name)
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                size_mb = os.path.getsize(path) / 1024 / 1024
                self.log(f'打包完成：{name}（{size_mb:.1f} MB）', 'ok')
                return name, path
        raise BuilderError('未找到打包生成的 exe，请查看上方打包日志。')

    def _upload(self, base_url, exe_path):
        url = base_url + UPLOAD_API
        name = os.path.basename(exe_path)
        size_mb = os.path.getsize(exe_path) / 1024 / 1024
        self.log(f'上传客户端到服务器（{size_mb:.1f} MB）：{url}')
        data = {}
        token = (self.token_var.get() or '').strip()
        if token:
            data[UPLOAD_TOKEN_FIELD] = token
        try:
            with open(exe_path, 'rb') as f:
                response = requests.post(
                    url, data=data,
                    files={'file': (name, f, 'application/octet-stream')},
                    timeout=(30, 900), verify=self._verify_tls())
        except requests.RequestException as exc:
            self.log(f'上传失败：{exc}', 'warn')
            self.log(f'请手动把 {name} 上传到你的服务器。', 'warn')
            return None

        if response.status_code in (404, 405):
            self.log('服务端没有 /upload_client_exe 接口，请先把最新版 app.py 部署到服务器，或手动上传。', 'warn')
            return None
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code == 200 and payload.get('status') == 'success':
            uploaded_name = payload.get('filename', name)
            self.log(f'上传成功，服务器文件名：{uploaded_name}', 'ok')
            return uploaded_name
        if response.status_code == 403:
            self.log('上传被拒绝：上传口令不正确。请在服务端设置 CLIENT_UPLOAD_TOKEN，并在本工具中填写相同口令。', 'warn')
            return None
        self.log(f'上传失败（状态码 {response.status_code}）：{response.text[:200]}', 'warn')
        self.log(f'请手动把 {name} 上传到你的服务器。', 'warn')
        return None


def main():
    enable_dpi_awareness()
    root = tk.Tk()
    CertificateBuilderApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
