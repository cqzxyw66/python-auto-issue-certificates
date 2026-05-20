#! /usr/env/python3
#! -*- coding: utf-8 -*-

from flask import Flask, render_template, request, Response, url_for
import json
from server.issue_certificate import certificate_issue
from cryptography.hazmat.primitives import serialization
from cryptography import x509
import sqlite3
import server.client_software_pyinstaller as client
import time

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html', title='证书域控管理平台')

@app.route('/issue_certificate', methods=['POST', 'GET'])
def issue_certificate():
    if request.method == 'POST':
        request_content = request.json
        csr = x509.load_pem_x509_csr(request_content.get('csr').encode())
        if not csr:
            return Response(status=400, mimetype='application/json', response=json.dumps({'error': 'CSR is required'}))
        cert_issue = certificate_issue()
        cert = cert_issue.create_certificate(csr)
        content = cert.public_bytes(serialization.Encoding.PEM).decode()
        with sqlite3.connect('config/database/database.db') as f:
            f.execute("INSERT INTO request_history (timestamp, username, ip_address, serial_number, domain, display_username, os, hostname, csr, private_key, certificate) VALUES (datetime('now', +'8 hours'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (request_content.get('username'), 
                       ','.join(request_content.get('ip_address')),
                       request_content.get('serial_number'), 
                       request_content.get('domain'), 
                       request_content.get('display_username'), 
                       request_content.get('os'),
                       request_content.get('hostname'),
                       request_content.get('csr'),
                       request_content.get('privatekey'),
                       content))
        with sqlite3.connect('config/database/database.db') as f:
            cursor = f.cursor()
            cursor.execute("INSERT INTO log (timestamp, action, username, details) VALUES (datetime('now', +'8 hours'), ?, ?, ?)", 
                      ('issue_certificate', 
                       request_content.get('username'), 
                       'Issued a certificate for ' + request_content.get('username')))
        return Response(status=200, mimetype='application/json', response=json.dumps({'certificate': content}))
    else:
        return 'Please send a POST request with the CSR in the form data.'
    
@app.route('/serialnumber_query', methods=['GET'])
def serialnumber_query():
    serial_number_query = request.args.get('serial_number')
    with sqlite3.connect('config/database/database.db') as f:
        cursor = f.cursor()
        cursor.execute("SELECT serial_number FROM serial_number where serial_number = ?", (serial_number_query,))
        serial_number = cursor.fetchall()
    if not serial_number:
        return Response(status=404, mimetype='application/json', response=json.dumps({'error': 'serial_number not found'}))
    return Response(status=200, mimetype='application/json', response=json.dumps({'status': 'success'}))

@app.route('/user_query', methods=['GET'])
def user_query():
    username_query = request.args.get('username')
    with sqlite3.connect('config/database/database.db') as f:
        cursor = f.cursor()
        cursor.execute("SELECT username,mail,status,when_expired FROM user where username = ?", (username_query,))
        userinfo = cursor.fetchall()
    if not userinfo:
        return Response(status=404, mimetype='application/json', response=json.dumps({'error': 'username not found'}))
    return Response(status=200, mimetype='application/json', response=json.dumps({'username': userinfo[0][0], 'email': userinfo[0][1], 'state': userinfo[0][2], 'when_expired': userinfo[0][3]}))

@app.route('/company_query', methods=['GET'])
def company_query():
    with sqlite3.connect('config/database/database.db') as f:
        cursor = f.cursor()
        cursor.execute("SELECT company_name,common_name FROM configuration")
        company_info = cursor.fetchall()
    return Response(status=200, mimetype='application/json', response=json.dumps({'company_name': company_info[0][0], 'common_name': company_info[0][1]}))

@app.route('/create_client_exe', methods=['GET'])
def create_client_exe():
    time.sleep(3)
    client.main()
    return Response(status=200, mimetype='application/json', response=json.dumps({'status': 'success'}))
    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)