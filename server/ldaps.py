#! /usr/bin/python3
#! -*- coding: utf-8 -*-

from ldap3 import Server, Connection, Tls, ALL
import ssl
import datetime
import sqlite3
import ldap3.core.exceptions

class ldap_connection():
    #初始化连接
    def __init__(self, ca_certs_file='config/domain_controller_certifiate.cer', port=636, server_address='ldaps://dc01.yangyuetong.com', domain='yangyuetong.com') -> None:
        self.port = port
        self.ca_certs_file = ca_certs_file
        self.dc = server_address
        self.domain = domain

    def __repr__(self) -> str:
        return str(self.result)
    
    # 根据用户定义的专用账号来查询users, 返回base_dn下面所有用户的信息
    def query(self, username, password, base_dn):
        server = Server(
            self.dc,
            get_info=ALL
        )
        conn = Connection(
            server,
            user=username + '@' + self.domain,
            password=password,
            auto_bind=True
        )

        search_filter = '(&(objectClass=user))'
        attributes = ['cn', 
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

    # 根据提供过来的账号密码来修改密码
    def modify_passwd(self, username, old_password, new_password, base_dn):
        server = Server(
            self.dc,
            get_info=ALL
        )
        try:
            conn = Connection(
                server, 
                user=username + '@' + self.domain,
                password=old_password, 
                auto_bind=True
                )
        except ldap3.core.exceptions.LDAPBindError:
            return '旧密码错误'

        conn.search(
            search_base=base_dn,
            search_filter=f'(&(objectClass=user)(sAMAccountName={username}))',
            attributes=['distinguishedName']
        )
        assert len(conn.entries) == 1
        user = conn.entries[0]['distinguishedName'].value
        result = conn.extend.microsoft.modify_password(
            user = user ,
            old_password = old_password,
            new_password = new_password
        )

        return result
        
# 查询并更新数据库
def main(username, password, server_address='ldaps://dc01.yangyuetong.com', port=636, ca_certs_file='config/domain_controller_certifiate.cer', domain='yangyuetong.com', base_dn='ou=home,dc=yangyuetong,dc=com'):
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
        status = 'enabled' if i['userAccountControl'].value == 512 else ('disabled' if i['userAccountControl'].value == 514 else 'disabled')

        user_info = i['sAMAccountName'].value, i['displayname'].value,i['mail'].value, status, i['telephoneNumber'].value,  when_expired, i['cn'].value, when_created, pwd_last_set
        user_result_from_ldaps.append(user_info)

    with sqlite3.connect('config/database/database.db') as f:
        name = [i[0] for i in user_result_from_ldaps]
        cursor = f.cursor()
        cursor.execute("SELECT username FROM user")
        query_result = cursor.fetchall()
        for i in query_result:
            if i[0] not in name:
                cursor.execute("UPDATE user SET status = 'deleted' WHERE username = ?", (i[0],))
        
        cursor.executemany("""
                        INSERT INTO user (username,displayname,role,mail,status,phone,when_expired,cn,when_created,pwd_last_set) VALUES (?,?,'user',?,?,?,?,?,?,?)
                        ON CONFLICT (username) DO UPDATE SET 
                        displayname = excluded.displayname,
                        mail = excluded.mail,
                        status = excluded.status,
                        phone = excluded.phone,
                        when_expired = excluded.when_expired,
                        cn = excluded.cn,
                        when_created = excluded.when_created,
                        pwd_last_set = excluded.pwd_last_set
                        """, 
                        user_result_from_ldaps)
        f.commit()

# 修改密码
def modify_password(username, 
                    old_password, 
                    new_password,server_address='ldaps://dc01.yangyuetong.com', 
                    port=636, 
                    ca_certs_file='config/domain_controller_certifiate.cer', 
                    domain='yangyuetong.com', 
                    base_dn='dc=yangyuetong,dc=com'
                    ):
    b = ldap_connection(ca_certs_file, port, server_address, domain)
    return b.modify_passwd(username, old_password, new_password, base_dn)

if __name__ == '__main__':
    result = modify_password('wangying2', old_password='Unis@123456', new_password='Unis@1234567')

    print(result)

    main('certificaterobot', 'Unis@123456', base_dn='ou=home,dc=yangyuetong,dc=com', domain='yangyuetong.com')