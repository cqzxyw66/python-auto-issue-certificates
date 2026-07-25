#! /usr/bin/python3
# -*- coding: utf-8 -*-

from ldap3 import Server, Connection, Tls, ALL
import ssl
import datetime
import sqlite3
import ldap3.core.exceptions
import os

DEFAULT_CA_CERT = 'config/domain_controller_certificate.cer'
LEGACY_CA_CERT = 'config/domain_controller_certifiate.cer'
DATABASE_PATH = 'config/database/database.db'


def _normalize_host(address):
    if address.startswith('ldaps://'):
        return address.split('://', 1)[1].rstrip('/')
    return address


def _tls_for_certificate(ca_certs_file):
    path = ca_certs_file
    if not os.path.exists(path) and os.path.exists(LEGACY_CA_CERT):
        path = LEGACY_CA_CERT
    if os.path.exists(path):
        return Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=path)
    return Tls(validate=ssl.CERT_NONE)


class ldap_connection():
    def __init__(self, ca_certs_file=DEFAULT_CA_CERT, port=636, server_address='ldaps://dc01.yangyuetong.com', domain='yangyuetong.com') -> None:
        self.port = port
        self.ca_certs_file = ca_certs_file
        self.dc = server_address
        self.domain = domain

    def __repr__(self) -> str:
        return str(getattr(self, 'result', ''))

    def _server(self):
        host = _normalize_host(self.dc)
        tls = _tls_for_certificate(self.ca_certs_file)
        return Server(host, port=self.port, use_ssl=True, get_info=ALL, tls=tls)

    def query(self, username, password, base_dn):
        server = self._server()
        conn = Connection(
            server,
            user=f"{username}@{self.domain}",
            password=password,
            auto_bind=True,
        )

        search_filter = '(&(objectClass=user))'
        attributes = [
            'cn',
            'sAMAccountName',
            'mail',
            'telephoneNumber',
            'displayname',
            'whenCreated',
            'pwdLastSet',
            'msDS-UserPasswordExpiryTimeComputed',
            'userAccountControl'
        ]

        conn.search(
            search_base=base_dn,
            search_filter=search_filter,
            attributes=attributes
        )

        self.result = conn.entries
        return conn.entries

    def modify_passwd(self, username, old_password, new_password, base_dn):
        server = self._server()
        try:
            conn = Connection(
                server,
                user=f"{username}@{self.domain}",
                password=old_password,
                auto_bind=True,
            )
        except ldap3.core.exceptions.LDAPBindError:
            return '旧密码错误'

        conn.search(
            search_base=base_dn,
            search_filter=f'(&(objectClass=user)(sAMAccountName={username}))',
            attributes=['distinguishedName']
        )
        if len(conn.entries) != 1:
            return '未找到用户对象'
        user_dn = conn.entries[0]['distinguishedName'].value
        try:
            result = conn.extend.microsoft.modify_password(
                user=user_dn,
                old_password=old_password,
                new_password=new_password
            )
            return result
        except Exception as exc:
            return str(exc)


def main(ca_certs_file=DEFAULT_CA_CERT):
    with sqlite3.connect(DATABASE_PATH) as f:
        cursor = f.cursor()
        cursor.execute("SELECT ldap_account_id,ldap_pwd,ldap_url,ldap_port,ldap_base_dn,common_name FROM configuration")
        company_info = cursor.fetchone()

    if not company_info:
        raise RuntimeError('缺少 LDAP 配置信息')

    username = company_info[0]
    password = company_info[1]
    server_address = company_info[2]
    port = int(company_info[3]) if company_info[3] else 636
    base_dn = company_info[4]
    domain = company_info[5]

    a = ldap_connection(ca_certs_file, port, server_address, domain)
    result = a.query(username, password, base_dn)
    user_result_from_ldaps = []
    for i in result:
        when_created = (i['whenCreated'].value + datetime.timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')
        pwd_last_set = (i['pwdLastSet'].value + datetime.timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')
        try:
            when_expired = datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=i['msDS-UserPasswordExpiryTimeComputed'].value / 10) + datetime.timedelta(hours=8)
        except OverflowError:
            when_expired = datetime.datetime(9999, 1, 1)
        when_expired = when_expired.strftime('%Y-%m-%d %H:%M:%S')
        user_account_control = int(i['userAccountControl'].value) if i['userAccountControl'] else 0
        if user_account_control == 512:
            status = 'enabled'
        elif user_account_control == 514:
            status = 'disabled'
        elif user_account_control == 66048:
            status = 'never expired'
        else:
            status = 'unknown'

        user_info = (
            i['sAMAccountName'].value,
            i['displayname'].value,
            i['mail'].value,
            status,
            i['telephoneNumber'].value,
            when_expired,
            i['cn'].value,
            when_created,
            pwd_last_set,
        )
        user_result_from_ldaps.append(user_info)

    with sqlite3.connect(DATABASE_PATH) as f:
        cursor = f.cursor()
        cursor.execute("SELECT username FROM user")
        query_result = [row[0] for row in cursor.fetchall()]
        for username in query_result:
            if username not in [item[0] for item in user_result_from_ldaps]:
                cursor.execute("UPDATE user SET status = 'deleted' WHERE username = ?", (username,))

        cursor.executemany(
            """
            INSERT INTO user (username, displayname, role, mail, status, phone, when_expired, cn, when_created, pwd_last_set)
            VALUES (?, ?, 'user', ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                displayname = excluded.displayname,
                mail = excluded.mail,
                status = excluded.status,
                phone = excluded.phone,
                when_expired = excluded.when_expired,
                cn = excluded.cn,
                when_created = excluded.when_created,
                pwd_last_set = excluded.pwd_last_set
            """,
            user_result_from_ldaps,
        )
        f.commit()


def modify_password(username,
                    old_password,
                    new_password,
                    ca_certs_file=DEFAULT_CA_CERT):
    with sqlite3.connect(DATABASE_PATH) as f:
        cursor = f.cursor()
        cursor.execute("SELECT ldap_url,ldap_port,ldap_base_dn,common_name FROM configuration")
        company_info = cursor.fetchone()

    if not company_info:
        raise RuntimeError('缺少 LDAP 配置信息')

    server_address = company_info[0]
    port = int(company_info[1]) if company_info[1] else 636
    base_dn = company_info[2]
    domain = company_info[3]

    b = ldap_connection(ca_certs_file, port, server_address, domain)
    return b.modify_passwd(username, old_password, new_password, base_dn)


if __name__ == '__main__':
    main()