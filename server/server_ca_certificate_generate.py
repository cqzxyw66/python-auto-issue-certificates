# /bin/env/python3
# -*- coding: utf-8 -*-

import sqlite3
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes
import datetime as dt

def main():
    #从数据库中读取企业的信息，包含公司名称，通用名称，邮箱，生成CA证书的CSR和KEY
    with sqlite3.connect('config/database/database.db') as f:
        cursor = f.cursor()
        cursor.execute("SELECT company_name,common_name,url FROM configuration")
        query_result = cursor.fetchall()

    country_name = 'CN'
    organization_name = query_result[0][1]
    organizational_unit_name = 'IT'
    common_name = 'ca.' + query_result[0][1]
    dns_name = query_result[0][2].split('//')[1].split(':')[0]

    #生成CA证书的CSR和KEY
    ca_country_name = x509.NameAttribute(x509.oid.NameOID.COUNTRY_NAME, country_name)
    ca_organization_name = x509.NameAttribute(x509.oid.NameOID.ORGANIZATION_NAME, organization_name)
    ca_organizational_unit_name = x509.NameAttribute(x509.oid.NameOID.ORGANIZATIONAL_UNIT_NAME, organizational_unit_name)
    ca_common_name = x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, common_name)
    ca_dns_name = x509.DNSName(dns_name)
    ca_subject = x509.Name([ca_country_name, ca_organization_name, ca_organizational_unit_name, ca_common_name])
    ca_subject_alternative = x509.SubjectAlternativeName([ca_dns_name])

    # 创建证书请求
    csr = x509.CertificateSigningRequestBuilder().subject_name(ca_subject)
    csr = csr.add_extension(ca_subject_alternative, critical=False)
    private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048
            )
    csr = csr.sign(private_key, hashes.SHA256())

    # 创建一个自签名的CA证书
    ca_cert = x509.CertificateBuilder().subject_name(
        ca_subject
    ).issuer_name(
        ca_subject
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        dt.datetime.now()
    ).not_valid_after(
        dt.datetime.now() + dt.timedelta(days=3650)
    ).add_extension(
        x509.BasicConstraints(ca=True, path_length=None), critical=True,
    ).sign(private_key, hashes.SHA256())

    # 将CSR和私钥写入文件，并先生成一份不公开用的自用签发
    with open('config/ca_private_key.pem', 'wb') as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ))
    with open('config/ca_csr.pem', 'wb') as f:
        f.write(csr.public_bytes(serialization.Encoding.PEM))

    with open('config/ca_certificate_self_signed.pem', 'wb') as f:
        f.write(ca_cert.public_bytes(serialization.Encoding.PEM))

if __name__ == '__main__':
    main()