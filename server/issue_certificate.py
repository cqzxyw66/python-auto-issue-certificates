#! /usr/bin/env python3
# -*- coding: utf-8 -*-

from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID, ExtensionOID
from cryptography.hazmat.primitives import serialization, hashes
import datetime
import os

class certificate_issue:
    def __init__(self):
        if os.path.exists('config/ca_private_key.pem'):
            with open('config/ca_private_key.pem', 'rb') as f:
                self.ca_private_key = serialization.load_pem_private_key(f.read(), password=None)
        else:
            raise FileNotFoundError('CA private key not found')
        if os.path.exists('config/ca_certificate.pem'):
            with open('config/ca_certificate.pem', 'rb') as f:
                self.ca_certificate = x509.load_pem_x509_certificate(f.read())
                self.ca_public_key = self.ca_certificate.public_key()
        else:
            raise FileNotFoundError('CA certificate not found')

    def __str__(self):
        return str(self)

    def create_certificate(self, csr):
        if isinstance(csr, bytes):
            csr = x509.load_pem_x509_csr(csr)

        try:
            csr_alt = csr.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
        except x509.ExtensionNotFound:
            csr_alt = None

        certificate_builder = x509.CertificateBuilder().subject_name(
            csr.subject
        ).issuer_name(
            self.ca_certificate.subject
        ).public_key(
            csr.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.datetime.now(datetime.timezone.utc)
        ).not_valid_after(
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)
        ).add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True
        ).add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH, ExtendedKeyUsageOID.EMAIL_PROTECTION, ExtendedKeyUsageOID.TIME_STAMPING]),
            critical=False
        )

        if csr_alt is not None:
            certificate_builder = certificate_builder.add_extension(
                x509.SubjectAlternativeName(csr_alt),
                critical=False
            )

        ee_cert = certificate_builder.sign(self.ca_private_key, hashes.SHA256())
        self.certificate = ee_cert
        return self.certificate

if __name__ == '__main__':
    cert_info = certificate_issue()
    print(cert_info)