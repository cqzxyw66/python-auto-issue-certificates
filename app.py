#! /usr/bin/python3
# -*- coding: utf-8 -*-

import base64
import io
import os
import sqlite3
import zipfile
from functools import wraps
from datetime import datetime, timedelta

import json

from flask import (
    Flask,
    Response,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
    jsonify,
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

from cryptography import x509
from cryptography.hazmat.primitives import serialization

import server.logo_icon as logo_icon
import server.email_notification as email_notification_module
import server.get_expired_person as get_expired_person_module
import server.issue_certificate as issue_certificate_module
import server.ldaps as ldaps_module
import server.login as login_module
import server.server_ca_certificate_generate as ca_generator
import server.server_init_database as server_init_database

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, 'config')
BUILDER_DIR = os.path.join(BASE_DIR)
DATABASE_DIR = os.path.join(CONFIG_DIR, 'database')
DATABASE_PATH = os.path.join(DATABASE_DIR, 'database.db')
ALLOWED_LOGO_EXTENSIONS = {'png', 'jpg', 'jpeg'}

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-secret')


def get_db_connection():
    os.makedirs(DATABASE_DIR, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_database():
    """确保数据库可用：全新环境（新容器、空的挂载卷）时自动建表并写入默认数据。

    注意：必须先确认表存在，再去查 configuration。数据库文件不存在时
    sqlite 会自动创建一个空文件，直接 SELECT 会报 "no such table"。
    """
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(DATABASE_DIR, exist_ok=True)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'configuration'")
        if cursor.fetchone() is None:
            # 数据库文件不存在或还是个空库，先把表结构建起来
            server_init_database.init_database(DATABASE_PATH)
        cursor.execute('SELECT COUNT(*) FROM configuration')
        if cursor.fetchone()[0] == 0:
            server_init_database.init_database(DATABASE_PATH)
        cursor.execute("SELECT COUNT(*) FROM user WHERE username = 'admin'")
        if cursor.fetchone()[0] == 0:
            server_init_database.init_database(DATABASE_PATH)
        conn.commit()


def blob_to_data_url(blob):
    if not blob:
        return None
    encoded = base64.b64encode(blob).decode('utf-8')
    mime = 'image/png' if blob[:8] == b'\x89PNG\r\n\x1a\n' else 'image/jpeg'
    return f'data:{mime};base64,{encoded}'


def allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_LOGO_EXTENSIONS


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return view(**kwargs)
    return wrapped_view


def admin_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if session.get('role') != 'admin':
            flash('需要管理员权限访问此页面。', 'warning')
            return redirect(url_for('overview'))
        return view(**kwargs)
    return wrapped_view


def get_current_user():
    username = session.get('username')
    if not username:
        return None
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM user WHERE username = ?', (username,))
        return cursor.fetchone()


def get_configuration():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM configuration LIMIT 1')
        row = cursor.fetchone()
    return dict(row) if row else None


def client_executable_name(configuration=None):
    """客户端 exe 的规范文件名（打包工具、上传接口与下载链接必须保持一致）。"""
    if configuration is None:
        configuration = get_configuration() or {}
    common_name = configuration.get('common_name') or 'client'
    return secure_filename(f'{common_name}_certificate_tool.exe') or 'certificate_tool.exe'


def write_log(action, username, details):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO log (timestamp, action, username, details) VALUES (datetime('now', '+8 hours'), ?, ?, ?)",
            (action, username, details),
        )
        conn.commit()


def count_certificates():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM request_history')
        return cursor.fetchone()[0]


def latest_logs(limit=5):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT timestamp, action, username, details FROM log ORDER BY id DESC LIMIT ?', (limit,))
        return cursor.fetchall()


def create_or_update_user(username, displayname=None, role='user', mail='', status='enabled'):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM user WHERE username = ?",
            (username,),
        )
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO user (username, displayname, role, mail, status, when_created, pwd_last_set) VALUES (?, ?, ?, ?, ?, datetime('now', '+8 hours'), datetime('now', '+8 hours'))",
                (username, displayname or username, role, mail, status),
            )
            conn.commit()


def save_logo_file(logo_file):
    if logo_file and logo_file.filename and allowed_image(logo_file.filename):
        filename = secure_filename(logo_file.filename)
        path = os.path.join(CONFIG_DIR, 'logo.png')
        logo_file.save(path)
        icon_path = os.path.join(CONFIG_DIR, 'logo.ico')
        try:
            logo_icon.png_to_ico(path, icon_path)
        except Exception:
            pass
        with open(path, 'rb') as f:
            logo_bytes = f.read()
        icon_bytes = None
        if os.path.exists(icon_path):
            import shutil
            shutil.copy(icon_path, os.path.join('static', 'favicon.ico'))
            with open(icon_path, 'rb') as f:
                icon_bytes = f.read()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE configuration SET company_logo = ?, logo = ? WHERE id = 1',
                (logo_bytes, icon_bytes),
            )
            conn.commit()
        return True
    return False


def configure_application_from_form(form):
    fields = [
        'company_name',
        'common_name',
        'url',
        'mail_id',
        'mail_pwd',
        'mail_server',
        'mail_server_port',
        'ldap_account_id',
        'ldap_pwd',
        'ldap_url',
        'ldap_port',
        'ldap_base_dn',
    ]
    values = [form.get(field, '').strip() for field in fields]
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            '''UPDATE configuration SET
                company_name = ?, common_name = ?, url = ?, mail_id = ?, mail_pwd = ?,
                mail_server = ?, mail_server_port = ?, ldap_account_id = ?, ldap_pwd = ?,
                ldap_url = ?, ldap_port = ?, ldap_base_dn = ? WHERE id = 1''',
            values,
        )
        conn.commit()


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash('请输入用户名和密码。', 'danger')
            return redirect(url_for('login'))

        if username == 'admin':
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM user WHERE username = ?', (username,))
                user_row = cursor.fetchone()
            if user_row:
                stored_pwd = user_row['password']
                # 先尝试哈希验证，失败则回退明文比对（兼容旧数据）
                password_ok = False
                if stored_pwd:
                    password_ok = check_password_hash(stored_pwd, password)
                if not password_ok:
                    password_ok = stored_pwd == password
                if password_ok:
                    # 如果是明文匹配成功，自动升级为哈希
                    if stored_pwd == password:
                        with get_db_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute(
                                "UPDATE user SET password = ? WHERE username = ?",
                                (generate_password_hash(password), 'admin'),
                            )
                            conn.commit()
                    session['username'] = username
                    session['role'] = user_row['role']
                    session['must_change_password'] = user_row['status'] == 'password_reset_required'
                    if user_row['status'] == 'password_reset_required':
                        return redirect(url_for('change_password'))
                    return redirect(url_for('overview'))

        authenticated = False
        try:
            authenticated = login_module.main(username, password)
        except Exception as e:
            flash('登录失败：%s' % str(e), 'danger')
            return redirect(url_for('login'))

        if not authenticated:
            flash('用户名或密码错误。', 'danger')
            return redirect(url_for('login'))

        create_or_update_user(username, displayname=username, role='user', status='enabled')
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT role FROM user WHERE username = ?', (username,))
            row = cursor.fetchone()
            role = row['role'] if row else 'user'
        session['username'] = username
        session['role'] = role
        session.pop('must_change_password', None)
        return redirect(url_for('overview'))

    return render_template('login.html', title='登录')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    return redirect(url_for('overview'))


@app.route('/overview')
@login_required
def overview():
    configuration = get_configuration()
    certificate_count = count_certificates()
    logs = latest_logs(5)
    company_logo_url = None
    if configuration:
        company_logo_url = blob_to_data_url(configuration.get('company_logo'))
    return render_template(
        'overview.html',
        title='总览',
        configuration=configuration,
        certificate_count=certificate_count,
        logs=logs,
        company_logo_url=company_logo_url,
    )


@app.route('/configuration', methods=['GET', 'POST'])
@login_required
@admin_required
def configuration():
    config = get_configuration()
    if request.method == 'POST':
        configure_application_from_form(request.form)
        if 'company_logo' in request.files:
            save_logo_file(request.files['company_logo'])
        flash('配置已保存。', 'success')
        write_log('update_configuration', session.get('username'), 'Updated system configuration')
        return redirect(url_for('configuration'))

    company_logo_url = blob_to_data_url(config.get('company_logo')) if config else None
    return render_template('configuration.html', title='企业配置', configuration=config, company_logo_url=company_logo_url)


@app.route('/users', methods=['GET', 'POST'])
@login_required
@admin_required
def users():
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        new_role = request.form.get('role')
        if user_id and new_role in ('admin', 'user'):
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT username FROM user WHERE id = ?', (user_id,))
                target_user = cursor.fetchone()
                if target_user:
                    cursor.execute('UPDATE user SET role = ? WHERE id = ?', (new_role, user_id))
                    conn.commit()
                    write_log('update_user_role', session.get('username'),
                              f'Changed role of {target_user["username"]} to {new_role}')
                    flash(f'用户 {target_user["username"]} 的角色已更新为 {new_role}。', 'success')
                else:
                    flash('用户不存在。', 'danger')
        return redirect(url_for('users'))

    # --- 查询过滤逻辑 ---
    search_username = request.args.get('username', '').strip()
    search_status = request.args.get('status', '').strip()
    search_pwd_from = request.args.get('pwd_last_set_from', '').strip()
    search_pwd_to = request.args.get('pwd_last_set_to', '').strip()
    search_created_from = request.args.get('when_created_from', '').strip()
    search_created_to = request.args.get('when_created_to', '').strip()
    search_expired_from = request.args.get('when_expired_from', '').strip()
    search_expired_to = request.args.get('when_expired_to', '').strip()

    conditions = []
    params = []

    if search_username:
        conditions.append('username LIKE ?')
        params.append(f'%{search_username}%')
    if search_status:
        conditions.append('status = ?')
        params.append(search_status)
    if search_pwd_from:
        conditions.append('pwd_last_set >= ?')
        params.append(search_pwd_from)
    if search_pwd_to:
        conditions.append('pwd_last_set <= ?')
        params.append(search_pwd_to + ' 23:59:59')
    if search_created_from:
        conditions.append('when_created >= ?')
        params.append(search_created_from)
    if search_created_to:
        conditions.append('when_created <= ?')
        params.append(search_created_to + ' 23:59:59')
    if search_expired_from:
        conditions.append('when_expired >= ?')
        params.append(search_expired_from)
    if search_expired_to:
        conditions.append('when_expired <= ?')
        params.append(search_expired_to + ' 23:59:59')

    where_clause = ' WHERE ' + ' AND '.join(conditions) if conditions else ''

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id, username, displayname, role, mail, status, when_created, pwd_last_set, when_expired FROM user'
            + where_clause + ' ORDER BY id ASC',
            params,
        )
        all_users = cursor.fetchall()

    return render_template(
        'users.html',
        title='用户管理',
        users=all_users,
        search_username=search_username,
        search_status=search_status,
        search_pwd_from=search_pwd_from,
        search_pwd_to=search_pwd_to,
        search_created_from=search_created_from,
        search_created_to=search_created_to,
        search_expired_from=search_expired_from,
        search_expired_to=search_expired_to,
    )


@app.route('/certificates', methods=['GET'])
@login_required
@admin_required
def certificates():
    config = get_configuration()
    cert_files = ['ca_private_key.pem', 'ca_csr.pem', 'ca_certificate.pem', 'domain_controller_certificate.cer']
    files_info = {}
    for filename in cert_files:
        filepath = os.path.join(CONFIG_DIR, filename)
        exists = os.path.exists(filepath)
        info = {'exists': exists, 'content': ''}
        if exists:
            with open(filepath, 'r', encoding='utf-8') as f:
                info['content'] = f.read()
        files_info[filename] = info

    return render_template('certificates.html', title='证书概览', configuration=config, files=files_info)


@app.route('/certificates/manage', methods=['GET', 'POST'])
@login_required
@admin_required
def certificates_manage():
    config = get_configuration()
    status = {}
    for filename in ['ca_csr.pem', 'ca_private_key.pem', 'ca_certificate.pem', 'domain_controller_certificate.cer']:
        status[filename] = os.path.exists(os.path.join(CONFIG_DIR, filename))

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'generate':
            try:
                ca_generator.main()
                flash('CA 私钥和 CSR 已生成。', 'success')
                write_log('generate_ca', session.get('username'), 'Generated CA CSR and private key')
            except Exception as exc:
                flash(f'生成 CA CSR 失败：{exc}', 'danger')
        elif action == 'paste_ca_cert':
            content = request.form.get('pem_content', '').strip()
            if content:
                with open(os.path.join(CONFIG_DIR, 'ca_certificate.pem'), 'w', encoding='utf-8') as f:
                    f.write(content)
                flash('CA 证书已保存。', 'success')
                write_log('paste_ca_certificate', session.get('username'), 'Pasted CA certificate')
            else:
                flash('内容不能为空。', 'danger')
        elif action == 'paste_dc':
            content = request.form.get('pem_content', '').strip()
            if content:
                with open(os.path.join(CONFIG_DIR, 'domain_controller_certificate.cer'), 'w', encoding='utf-8') as f:
                    f.write(content)
                flash('域控证书已保存。', 'success')
                write_log('paste_dc_certificate', session.get('username'), 'Pasted domain controller certificate')
            else:
                flash('内容不能为空。', 'danger')
        return redirect(url_for('certificates_manage'))

    return render_template('certificates_manage.html', title='证书管理', configuration=config, status=status)


@app.route('/software', methods=['GET'])
@login_required
def software():
    """软件管理：展示/下载客户端 exe，并指引管理员在 Windows 上打包。

    服务端通常部署在 Linux/Docker 上，无法交叉编译出 Windows exe，
    因此客户端程序由管理员用「客户端打包工具」在 Windows 本机生成，
    再通过工具自动上传（或手动放置）到 config 目录。
    """
    configuration = get_configuration() or {}
    executable_name = client_executable_name(configuration)
    executable_path = os.path.join(CONFIG_DIR, executable_name)
    exists = os.path.exists(executable_path)

    executable_info = None
    if exists:
        stat_result = os.stat(executable_path)
        executable_info = {
            'size': f'{stat_result.st_size / 1024 / 1024:.1f} MB',
            'updated_at': datetime.fromtimestamp(stat_result.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
        }

    # 管理员打包工具：由开发者预先打包好，放到 config 目录后即可在此分发
    builder_name = 'certificate_builder.exe'
    builder_path = os.path.join(BUILDER_DIR, builder_name)
    builder_exists = os.path.exists(builder_path)
    builder_size = f'{os.path.getsize(builder_path) / 1024 / 1024:.1f} MB' if builder_exists else None

    return render_template('software.html', title='软件管理', configuration=configuration,
                           executable_name=executable_name, exists=exists,
                           executable_info=executable_info, builder_name=builder_name,
                           builder_exists=builder_exists, builder_size=builder_size)


@app.route('/issue_certificate', methods=['POST', 'GET'])
def issue_certificate():
    if request.method == 'GET':
        return 'Please send a POST request with the CSR in the form data.'

    request_content = request.json
    csr = None
    if request_content:
        csr_pem = request_content.get('csr')
        if csr_pem:
            try:
                csr = x509.load_pem_x509_csr(csr_pem.encode())
            except Exception:
                csr = None

    if not csr:
        return Response(status=400, mimetype='application/json', response=json.dumps({'error': 'CSR is required'}))

    cert_issue = issue_certificate_module.certificate_issue()
    cert = cert_issue.create_certificate(csr)
    content = cert.public_bytes(serialization.Encoding.PEM).decode()

    ip_address = request_content.get('ip_address') if request_content else None
    if isinstance(ip_address, list):
        ip_address_value = ','.join(ip_address)
    else:
        ip_address_value = str(ip_address or '')

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO request_history (timestamp, username, ip_address, serial_number, domain, display_username, os, hostname, csr, private_key, certificate) VALUES (datetime('now', '+8 hours'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                request_content.get('username') if request_content else None,
                ip_address_value,
                request_content.get('serial_number') if request_content else None,
                request_content.get('domain') if request_content else None,
                request_content.get('display_username') if request_content else None,
                request_content.get('os') if request_content else None,
                request_content.get('hostname') if request_content else None,
                request_content.get('csr') if request_content else None,
                request_content.get('privatekey') if request_content else None,
                content,
            ),
        )
        conn.commit()

    write_log(
        'issue_certificate',
        request_content.get('username', 'unknown') if request_content else 'unknown',
        'Issued a certificate for ' + (request_content.get('username') if request_content else 'unknown'),
    )
    return Response(status=200, mimetype='application/json', response=json.dumps({'certificate': content}))


@app.route('/serialnumber_query', methods=['GET'])
def serialnumber_query():
    serial_number_query = request.args.get('serial_number')
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT serial_number FROM serial_number WHERE serial_number = ?', (serial_number_query,))
        serial_number = cursor.fetchall()
    if not serial_number:
        return Response(status=404, mimetype='application/json', response=json.dumps({'error': 'serial_number not found'}))
    return Response(status=200, mimetype='application/json', response=json.dumps({'status': 'success'}))


@app.route('/user_query', methods=['GET'])
def user_query():
    username_query = request.args.get('username')
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT username, mail, status, when_expired FROM user WHERE username = ?', (username_query,))
        userinfo = cursor.fetchall()
    if not userinfo:
        return Response(status=404, mimetype='application/json', response=json.dumps({'error': 'username not found'}))
    return Response(status=200, mimetype='application/json', response=json.dumps({'username': userinfo[0][0], 'email': userinfo[0][1], 'state': userinfo[0][2], 'when_expired': userinfo[0][3]}))


@app.route('/company_query', methods=['GET'])
def company_query():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT company_name, common_name, url FROM configuration')
        company_info = cursor.fetchall()
    return Response(status=200, mimetype='application/json', response=json.dumps({'company_name': company_info[0][0], 'common_name': company_info[0][1], 'url': company_info[0][2]}))


# 客户端打包源码：管理员在自己的 Windows 电脑上用打包工具下载后执行 PyInstaller
CLIENT_BUILD_SOURCE_FILES = (
    'client_software_pyinstaller_new.py',
    'client_exe.py',
    'get_computer_info.py',
    'create_certificate.py',
)


@app.route('/client_source_package', methods=['GET'])
def client_source_package():
    """把打包客户端所需的源码打成 zip，供管理员的打包工具下载。

    线上环境（Linux/Docker）无法交叉编译出 Windows 的 exe，
    因此由管理员在 Windows 本机执行打包，这里只负责提供源码。
    """
    client_dir = os.path.join(BASE_DIR, 'client')
    logo_path = os.path.join(CONFIG_DIR, 'logo.ico')
    missing = [name for name in CLIENT_BUILD_SOURCE_FILES if not os.path.exists(os.path.join(client_dir, name))]
    if not os.path.exists(logo_path):
        missing.append('logo.ico')
    if missing:
        return jsonify(status='fail', message='服务端缺少文件：' + '、'.join(missing)), 500

    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for name in CLIENT_BUILD_SOURCE_FILES:
            bundle.write(os.path.join(client_dir, name), name)
        bundle.write(logo_path, 'logo.ico')
        # 打包脚本要求 config 目录存在，并会在结束后清空其中内容
        bundle.writestr('config/.keep', '')
    memory_file.seek(0)

    write_log('download_client_source', 'certificate_builder', 'Downloaded client build source package')
    return send_file(memory_file, mimetype='application/zip', as_attachment=True,
                     download_name='client_build_sources.zip')


@app.route('/upload_client_exe', methods=['POST'])
def upload_client_exe():
    """接收管理员打包工具上传的客户端 exe，保存到 config 目录供下载。

    安全提示：该接口默认不校验口令（方便打包工具直接调用）。
    如需限制，请在服务端设置环境变量 CLIENT_UPLOAD_TOKEN，
    并在打包工具中填写相同口令。
    """
    required_token = os.environ.get('CLIENT_UPLOAD_TOKEN', '').strip()
    if required_token and request.form.get('token', '').strip() != required_token:
        return jsonify(status='fail', message='上传口令不正确'), 403

    uploaded = request.files.get('file')
    if uploaded is None or not uploaded.filename:
        return jsonify(status='fail', message='未收到上传文件'), 400
    if not uploaded.filename.lower().endswith('.exe'):
        return jsonify(status='fail', message='只允许上传 exe 文件'), 400

    filename = client_executable_name()
    target_path = os.path.join(CONFIG_DIR, filename)
    uploaded.save(target_path)

    size = os.path.getsize(target_path)
    write_log('upload_client_exe', 'certificate_builder', f'Uploaded client executable: {filename} ({size} bytes)')
    return jsonify(status='success', filename=filename, size=size)


@app.route('/history')
@login_required
def history():
    username = session.get('username')
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if session.get('role') == 'admin':
            cursor.execute('SELECT * FROM request_history ORDER BY id DESC LIMIT 100')
        else:
            cursor.execute('SELECT * FROM request_history WHERE username = ? ORDER BY id DESC LIMIT 100', (username,))
        entries = cursor.fetchall()
    return render_template('history.html', title='证书颁发', entries=entries)


@app.route('/logs')
@login_required
@admin_required
def logs():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM log ORDER BY id DESC LIMIT 100')
        entries = cursor.fetchall()
    return render_template('logs.html', title='系统日志', entries=entries)


@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    current_user = get_current_user()
    if not current_user:
        return redirect(url_for('login'))

    if request.method == 'POST':
        old_password = request.form.get('old_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not old_password or not new_password or not confirm_password:
            flash('请填写所有密码字段。', 'danger')
            return redirect(url_for('change_password'))
        if new_password != confirm_password:
            flash('两次输入的新密码不一致。', 'danger')
            return redirect(url_for('change_password'))

        if session.get('username') == 'admin':
            stored_pwd = current_user['password']
            # 先尝试哈希验证，失败则回退明文比对（兼容旧数据）
            password_ok = False
            if stored_pwd:
                password_ok = check_password_hash(stored_pwd, old_password)
            if not password_ok:
                password_ok = stored_pwd == old_password
            if not password_ok:
                flash('旧密码不正确。', 'danger')
                return redirect(url_for('change_password'))
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE user SET password = ?, status = 'enabled', pwd_last_set = datetime('now', '+8 hours') WHERE username = ?",
                    (generate_password_hash(new_password), 'admin'),
                )
                conn.commit()
            flash('本地管理员密码已更新。', 'success')
            write_log('change_password', session.get('username'), 'Changed local admin password')
            return redirect(url_for('overview'))

        try:
            result = ldaps_module.modify_password(session.get('username'), old_password, new_password)
            if result is True or result is None:
                flash('域密码已修改。', 'success')
                write_log('change_password', session.get('username'), 'Changed domain password')
                return redirect(url_for('overview'))
            flash(f'密码修改失败：{result}', 'danger')
        except Exception as exc:
            flash(f'密码修改失败：{exc}', 'danger')
        return redirect(url_for('change_password'))

    return render_template('change_password.html', title='修改密码', current_user=current_user)


@app.route('/download/<path:filename>')
@login_required
def download(filename):
    filename = secure_filename(filename)
    allowed_names = {
        'ca_csr.pem',
        'ca_private_key.pem',
        'ca_certificate.pem',
        'domain_controller_certificate.cer',
    }
    if filename not in allowed_names and not filename.endswith('.exe'):
        flash('不支持的下载文件。', 'danger')
        return redirect(url_for('overview'))

    # 打包工具 exe 存放在 client_config 目录，其余证书/客户端文件存放在 config 目录
    download_dir = BUILDER_DIR if filename == 'certificate_builder.exe' else CONFIG_DIR
    file_path = os.path.join(download_dir, filename)
    if not os.path.exists(file_path):
        flash('文件未找到。', 'danger')
        return redirect(url_for('overview'))
    return send_from_directory(download_dir, filename, as_attachment=True)


def sync_users():
    try:
        ldaps_module.main()
        write_log('sync_users', 'system', 'Synchronized users from LDAP')
    except Exception as exc:
        write_log('sync_users_failed', 'system', f'LDAP sync failed: {exc}')


def send_password_notifications():
    try:
        expired_json = get_expired_person_module.main()
        if expired_json:
            import json
            expired_persons = json.loads(expired_json)
            if expired_persons:
                email_notification_module.main(expired_persons)
                write_log('email_notifications', 'system', 'Sent password expiry notifications')
    except Exception as exc:
        write_log('email_notification_failed', 'system', f'Email notification failed: {exc}')


def initialize_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler(timezone='Asia/Shanghai')
        scheduler.add_job(sync_users, 'cron', hour=1, minute=0)
        scheduler.add_job(send_password_notifications, 'cron', hour=2, minute=0)
        scheduler.start()
    except Exception:
        pass


_database_checked = False


@app.before_request
def ensure_started():
    """兜底：以 flask run / gunicorn 等方式启动时（不会走 __main__），也要保证数据库已初始化。"""
    global _database_checked
    if not _database_checked:
        ensure_database()
        _database_checked = True


if __name__ == '__main__':
    ensure_database()
    initialize_scheduler()
    app.run(host='0.0.0.0', port=5000, debug=True)
