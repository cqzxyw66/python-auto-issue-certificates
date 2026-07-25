#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sqlite3
import ssl
from ldap3 import Server, Connection, ALL, Tls

DATABASE_PATH = 'config/database/database.db'
DOMAIN_CONTROLLER_CERT = 'config/domain_controller_certificate.cer'
LEGACY_DC_CERT = 'config/domain_controller_certifiate.cer'


def _load_configuration():
    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ldap_url, ldap_port, ldap_base_dn, common_name FROM configuration LIMIT 1")
        row = cursor.fetchone()
        if not row:
            raise RuntimeError('缺少配置信息，请先配置系统。')
        return {
            'ldap_url': row[0],
            'ldap_port': int(row[1]) if row[1] else 636,
            'ldap_base_dn': row[2],
            'domain': row[3],
        }


def _parse_server_address(url):
    if not url:
        return 'localhost'
    if url.startswith('ldaps://'):
        return url.split('://', 1)[1].rstrip('/')
    return url


def _tls_config():
    cert_file = DOMAIN_CONTROLLER_CERT
    if not os.path.exists(cert_file) and os.path.exists(LEGACY_DC_CERT):
        cert_file = LEGACY_DC_CERT
    if os.path.exists(cert_file):
        return Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=cert_file)
    return Tls(validate=ssl.CERT_NONE)


def main(username, password):
    config = _load_configuration()
    host = _parse_server_address(config['ldap_url'])
    tls = _tls_config()
    server = Server(host, port=config['ldap_port'], use_ssl=True, get_info=ALL, tls=tls)
    try:
        conn = Connection(
            server,
            user=f"{username}@{config['domain']}",
            password=password,
            auto_bind=True,
        )
        return conn.bound
    except Exception:
        return False


if __name__ == '__main__':
    print(main('certificaterobot', 'Unis@123456'))