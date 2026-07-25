#! /bin/env/python3
# -*- coding: utf-8 -*-

import sqlite3

DATABASE_PATH = 'config/database/database.db'


def init_database():
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS request_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp timestamp,
                        hostname TEXT,
                        ip_address TEXT,
                        serial_number TEXT,
                        domain TEXT,
                        username TEXT,
                        display_username TEXT,
                        os TEXT,
                        csr TEXT,
                        private_key TEXT,
                        certificate TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS configuration (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        company_name TEXT not null,
                        company_logo BLOB,
                        common_name TEXT not null,
                        logo BLOB,
                        url TEXT,
                        mail_id,
                        mail_pwd,
                        mail_server,
                        mail_server_port,
                        ldap_account_id,
                        ldap_pwd,
                        ldap_url,
                        ldap_port,
                        ldap_base_dn)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE not null,
                        password TEXT,
                        displayname TEXT,
                        role TEXT,
                        mail TEXT,
                        status TEXT,
                        phone TEXT,
                        when_expired TEXT,
                        cn TEXT,
                        when_created TEXT,
                        pwd_last_set TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp timestamp,
                        action TEXT,
                        username TEXT,
                        details TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS serial_number (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        serial_number TEXT UNIQUE)''')

    cursor.execute('SELECT COUNT(*) FROM configuration')
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            '''INSERT INTO configuration (
                    company_name, common_name, url,
                    mail_id, mail_pwd, mail_server, mail_server_port,
                    ldap_account_id, ldap_pwd, ldap_url, ldap_port, ldap_base_dn
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                'Your Company', 'yourdomain.com', 'http://127.0.0.1:5000',
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

    cursor.close()
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_database()
