#! /usr/env/python3
#! -*- coding: utf-8 -*-

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
import os
import subprocess
import client.get_computer_info as get_computer_info

class certificate_generate:
    def __init__(self):
        self.certificate = None
        #生成密钥对
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048
        )
        # 私钥写入到属性
        self.private_key = private_key

    def __str__(self):
        return str(self)
    
    def check_certificate(self):
        command = 'get-childitem -path cert:\\currentuser\\my | where-object {{ $_.subject -like \'*{0}*\' }} | format-list'.format(computer_info['username'])
        result = subprocess.check_output(['powershell', '-Command', command], shell=True)
        certificate_username = result.decode('utf-8').strip().splitlines()[0].split(':')[1].strip()
        certificate_notafter = result.decode('utf-8').strip().splitlines()[4].split(':', maxsplit=1)[1].strip()
        return (certificate_username, certificate_notafter)
    
    def create_csr(self, country_name, organization_name, common_name, organizational_unit_name, email_list):

        # 创建证书请求要素
        country_name = x509.NameAttribute(x509.oid.NameOID.COUNTRY_NAME, country_name)
        organization_name = x509.NameAttribute(x509.oid.NameOID.ORGANIZATION_NAME, organization_name)
        common_name = x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, common_name)
        organizational_unit_name = x509.NameAttribute(x509.oid.NameOID.ORGANIZATIONAL_UNIT_NAME, organizational_unit_name)
        subject = x509.Name([country_name, organization_name, common_name, organizational_unit_name])
        subject_alternative = x509.SubjectAlternativeName([x509.RFC822Name(email) for email in email_list])

        # 创建证书请求
        csr = x509.CertificateSigningRequestBuilder().subject_name(subject)
        csr = csr.add_extension(subject_alternative, critical=True)
        csr = csr.sign(self.private_key, hashes.SHA256())
        self.req = csr
        return csr
    
    def request_certificate(self, csr, URL='http://localhost:5000/issue_certificate',**kwargs):
        # 将CSR发送到服务器并获取证书
        import requests
        headers = {'Content-Type': 'application/json'}
        data = {'csr': csr.public_bytes(serialization.Encoding.PEM).decode(),
                **kwargs}
        response = requests.post(URL, json=data, headers=headers)
        if response.status_code == 200:
            cert_pem = response.json().get('certificate')
            cert = x509.load_pem_x509_certificate(cert_pem.encode())
            self.certificate = cert
            return cert
        else:
            raise Exception('Failed to request certificate: {}'.format(response.text))
    
    def create_pfx(self, certificate, private_key):
        private_key = self.private_key
        pfx = pkcs12.serialize_key_and_certificates(
            name=bytes(certificate.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value, 'utf-8'),
            key=private_key,
            cert=certificate,
            cas=None,
            encryption_algorithm=serialization.BestAvailableEncryption('54661582'.encode())
        )
        os.makedirs(r'c:\cert_temp', exist_ok=True)
        with open(r'c:\cert_temp\issued_cert.pfx', 'wb') as f:
            f.write(pfx)

    def import_pfx(self, pfx_path=r'c:\cert_temp\issued_cert.pfx', password='54661582'):
        # 将证书和私钥导入到当前用户的个人证书存储区
        cert_path = pfx_path
        command = 'Import-PfxCertificate -FilePath "{0}" -Password (ConvertTo-SecureString -String "{1}" -AsPlainText -Force) -CertStoreLocation "Cert:\\CurrentUser\\My"'.format(cert_path, password)
        subprocess.run(['powershell', '-Command', command], shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.remove(cert_path)
        os.removedirs(r'c:\cert_temp')

if __name__ == "__main__":
    import requests
    url = 'http://localhost:5000'
    computer_info = get_computer_info.computer_info().get_computer_info()
    computer_query = requests.get(f'{url}/serialnumber_query?serial_number={computer_info["serial_number"]}')
    user_query = requests.get('http://localhost:5000/user_query?username=%s' % computer_info['username'])
    if computer_query.status_code == 404:
        raise Exception('serial_number not found')
    elif user_query.status_code == 404:
        raise Exception('username not found')
    else:
        certificate_gen = certificate_generate()
        cert_csr = certificate_gen.create_csr(
            country_name='CN', 
            organization_name=computer_info['domain'], 
            common_name=computer_info['username'], 
            organizational_unit_name='IT', 
            email_list=[user_query.json()['email']]
        )
        private_key_bytes = certificate_gen.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode('utf-8')
        cert = certificate_gen.request_certificate(
            csr=cert_csr, 
            **{
                'username': computer_info['username'], 
                'ip_address': computer_info['ip_address'], 
                'serial_number': computer_info['serial_number'], 
                'domain': computer_info['domain'], 
                'display_username': computer_info['display_username'], 
                'os': computer_info['os'], 
                'hostname': computer_info['hostname'], 
                'privatekey': private_key_bytes
            }
        )

        certificate_gen.create_pfx(certificate=cert, private_key=certificate_gen.private_key)
        certificate_gen.import_pfx()