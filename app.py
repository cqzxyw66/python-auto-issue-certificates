#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import os
import sqlite3
from functools import wraps
from datetime import datetime, timedelta

import json
import time

from flask import (
    Flask,
    Response,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
    jsonify,
)
from werkzeug.utils import secure_filename

from cryptography import x509
from cryptography.hazmat.primitives import serialization

import config.logo_icon as logo_icon
import server.client_software_pyinstaller as client_builder
import server.email_notification as email_notification_module
import server.get_expired_person as get_expired_person_module
import server.issue_certificate as issue_certificate_module
import server.ldaps as ldaps_module
import server.login as login_module
import server.server_ca_certificate_generate as ca_generator
import server.server_init_database as server_init_database

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, 'config')
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
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(DATABASE_DIR, exist_ok=True)
    server_init_database.init_database()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM configuration')
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                '''INSERT INTO configuration (
                    company_name, company_logo, common_name, logo, url,
                    mail_id, mail_pwd, mail_server, mail_server_port,
                    ldap_account_id, ldap_pwd, ldap_url, ldap_port, ldap_base_dn
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    'Your Company', None, 'yourdomain.com', None, 'http://127.0.0.1:5000',
                    'admin@example.com', '', 'smtp.example.com', '465',
                    '', '', 'ldaps://localhost', 636, 'dc=example,dc=com',
                ),
            )
        cursor.execute("SELECT COUNT(*) FROM user WHERE username = 'admin'")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "INSERT INTO user (username, password, displayname, role, mail, status, when_created, pwd_last_set) VALUES (?, ?, ?, ?, ?, ?, datetime('now', '+8 hours'), datetime('now', '+8 hours'))",
                ('admin', 'admin123', 'Administrator', 'admin', 'admin@localhost', 'password_reset_required'),
            )
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
            if user_row and user_row['password'] == password:
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
    return render_template('configuration.html', title='配置', configuration=config, company_logo_url=company_logo_url)


@app.route('/certificates', methods=['GET', 'POST'])
@login_required
@admin_required
def certificates():
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
        elif action == 'upload_ca' and 'ca_certificate' in request.files:
            uploaded_file = request.files['ca_certificate']
            if uploaded_file and uploaded_file.filename:
                uploaded_file.save(os.path.join(CONFIG_DIR, 'ca_certificate.pem'))
                flash('CA 证书已上传。', 'success')
                write_log('upload_ca_certificate', session.get('username'), 'Uploaded CA certificate')
        elif action == 'upload_dc' and 'dc_certificate' in request.files:
            uploaded_file = request.files['dc_certificate']
            if uploaded_file and uploaded_file.filename:
                uploaded_file.save(os.path.join(CONFIG_DIR, 'domain_controller_certificate.cer'))
                flash('域控证书已上传。', 'success')
                write_log('upload_dc_certificate', session.get('username'), 'Uploaded domain controller certificate')
        return redirect(url_for('certificates'))

    return render_template('certificates.html', title='证书配置', configuration=config, status=status)


@app.route('/software', methods=['GET', 'POST'])
@login_required
@admin_required
def software():
    config = get_configuration()
    executable_name = None
    if config and config.get('common_name'):
        executable_name = f"{config.get('common_name')}_certificate_tool.exe"
    executable_path = os.path.join(CONFIG_DIR, executable_name) if executable_name else None
    exists = executable_path and os.path.exists(executable_path)

    if request.method == 'POST':
        try:
            client_builder.main()
            flash('客户端软件已生成。', 'success')
            write_log('generate_software', session.get('username'), f'Generated client software: {executable_name}')
        except Exception as exc:
            flash(f'生成客户端软件失败：{exc}', 'danger')
        return redirect(url_for('software'))

    return render_template('software.html', title='软件下载', executable_name=executable_name, exists=exists)


@app.route('/create_client_exe', methods=['GET'])
@login_required
@admin_required
def create_client_exe():
    time.sleep(3)
    client_builder.main()
    return Response(status=200, mimetype='application/json', response=json.dumps({'status': 'success'}))


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
        cursor.execute('SELECT company_name, common_name FROM configuration')
        company_info = cursor.fetchall()
    return Response(status=200, mimetype='application/json', response=json.dumps({'company_name': company_info[0][0], 'common_name': company_info[0][1]}))


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
    return render_template('history.html', title='历史记录', entries=entries)


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
            if current_user['password'] != old_password:
                flash('旧密码不正确。', 'danger')
                return redirect(url_for('change_password'))
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE user SET password = ?, status = 'enabled', pwd_last_set = datetime('now', '+8 hours') WHERE username = ?",
                    (new_password, 'admin'),
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
    file_path = os.path.join(CONFIG_DIR, filename)
    if not os.path.exists(file_path):
        flash('文件未找到。', 'danger')
        return redirect(url_for('overview'))
    return send_from_directory(CONFIG_DIR, filename, as_attachment=True)


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


@app.before_request
def ensure_started():
    if not os.path.exists(DATABASE_PATH):
        ensure_database()


if __name__ == '__main__':
    ensure_database()
    initialize_scheduler()
    app.run(host='0.0.0.0', port=5000, debug=True)
