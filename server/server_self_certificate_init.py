#! /usr/bin/python3
#! -*- coding: utf-8 -*-

from server.issue_certificate import certificate_issue
from client.create_certificate import certificate_generate
import sqlite3
from cryptography.hazmat.primitives import serialization

#先生成csr，然后调用issue_certificate.py中的create_certificate方法，生成一个合法证书
def main():
    #从数据库中读取企业的信息，包含公司名称，通用名称，邮箱
    with sqlite3.connect('config/database/database.db') as f:
        cursor = f.cursor()
        cursor.execute("SELECT company_name,url,root_mail FROM configuration")
        query_result = cursor.fetchall()

    country_name = 'CN'
    organization_name = query_result[0][0]
    common_name = query_result[0][1].split('//')[1].split(':')[0]
    mail = [query_result[0][2]]

    csr_info = certificate_generate()
    csr_csr = csr_info.create_csr(country_name,organization_name,common_name,'IT',mail)
    csr_private_key = csr_info.private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')

    cert_info = certificate_issue()
    cert_info.create_certificate(csr_csr)

    with open('config/ca_self_used_3rd_cert_key.pem', 'wb') as f:
        f.write(csr_private_key.encode('utf-8'))
    with open('config/ca_self_used_3rd_cert_cert.pem', 'wb') as f:
        f.write(cert_info.certificate.public_bytes(serialization.Encoding.PEM))

if __name__ == '__main__':
    main()