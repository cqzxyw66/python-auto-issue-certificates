#! /bin/env/python3
#! -*- coding: utf-8 -*-

from ldap3 import Server, Connection, ALL
import sqlite3

def main(username, password):
    with sqlite3.connect('config/database/database.db') as f:
        cursor = f.cursor()
        cursor.execute("SELECT ldap_url,ldap_port,ldap_base_dn,common_name FROM configuration")
        company_info = cursor.fetchall()
    
    server_address = company_info[0][0]
    port = company_info[0][1]
    base_dn = company_info[0][2]
    domain = company_info[0][3]

    server = Server(
        server_address,
        get_info=ALL
    )

    conn = Connection(
        server,
        user=username + '@' + domain,
        password=password
    )
    
    result = conn.bind()

    if result:
        return '登录成功'
    else:
        return '账号密码错误'
    
    
if __name__ == '__main__':
    print(main('certificaterobot', 'Unis@123456'))