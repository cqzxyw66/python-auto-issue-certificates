#! /usr/env/python3
#! -*- coding: utf-8 -*-

import subprocess
import tkinter as tk
from tkinter import messagebox
import client.get_computer_info as get_computer_info
import requests
import datetime
import client.create_certificate as create_certificate
from cryptography.hazmat.primitives import serialization
import config.logo_icon as logo_icon

#获取参数传进来的企业信息
name = '重庆悦潼科技有限公司'
domain = 'yangyuetong.com'
url = 'http://localhost:5000'

window = tk.Tk()
window.title(f'{name}证书申请工具')

#获取屏幕的宽度和高度
screen_width = window.winfo_screenwidth()
screen_height = window.winfo_screenheight()

#设置窗口的宽度和高度
window_width = 550
window_height = 220

#定义窗口初始化的位置,宽度x高度+x偏移+y偏移
window.geometry(f'{window_width}x{window_height}+{int((screen_width - window_width) / 2)}+{int((screen_height - window_height) / 2)}')
window.rowconfigure(5, weight=1)
window.columnconfigure(3, weight=1)
window.minsize(window_width, window_height)
var_out = tk.StringVar()

#设置图标
logo_icon = logo_icon.png_to_ico('config/logo.png', 'config/logo.ico')
img = tk.PhotoImage(data=logo_icon)
window.iconphoto(True, img)

#获取账号有效期
def get_account_when_expired(username):
    url_query = url + '/user_query'
    response = requests.get(url_query, params={'username': username})
    if response.status_code == 200:
        return response.json().get('when_expired')
    else:
        return '不存在'

#获取当前电脑证书情况
def get_certificate_status(username) -> str:
    command = 'get-childitem -path cert:\\currentuser\\my | where-object {{ $_.subject -like \'*{0}*\' -and $_.subject -like \'*OU*CN*O*C*\' }} | format-list'.format(username)
    result = subprocess.check_output(['powershell', '-Command', command], shell=True)
    if result:
        result = result.decode('utf-8').strip().splitlines()[5].split(':', maxsplit=1)[1].replace('/','-').strip()
        return '存在，有效期至：' + result
    else:
        return '未发现证书'

#获取电脑序列号是否存在
def get_serial_number_status(serial_number):
    url_query = url + '/serialnumber_query'
    response = requests.get(url_query, params={'serial_number': serial_number})
    if response.status_code == 200 and response.json().get('status') == 'success':
        return 'OK'
    else:
        return 'Fail'
    
#获取公司域名
def get_domain():
    url_query = url + '/company_query'
    response = requests.get(url_query)
    if response.status_code == 200:
        return response.json().get('common_name')
    else:
        return '不存在'

#开始按钮
def start_button():
    global computer_info
    computer_info = get_computer_info.computer_info().get_computer_info()
    #开始按钮点击后，清空之前的信息
    label_account_value.config(text='')
    label_domain_value.config(text='')
    label_serialnumber_status.config(text='')
    label_account_status.config(text='')
    label_domain_status.config(text='')
    label_certificate_status.config(text='')
    button_request.config(state='disabled')

    #每次点击，先本地检查序列号和证书情况
    label_serialnumber_value.config(text=computer_info['serial_number'])
    label_certificate_value.config(text=get_certificate_status((computer_info['username'])))
    #检查网络连接
    try:
        requests.get(url, timeout=1)
    except requests.exceptions.ConnectionError:
        messagebox_network_fail()
        return
    
    label_account_value.config(text=computer_info['username'] +', 有效期至：' + get_account_when_expired(computer_info['username']))
    label_domain_value.config(text=computer_info['domain'])
    # label_domain_value.config(text='yangyuetong.com') 测试代码
    get_serial_number_result = get_serial_number_status(computer_info['serial_number'])
    label_serialnumber_status.config(text=get_serial_number_result, fg='green' if get_serial_number_result == 'OK' else 'red')
    # label_serialnumber_status.config(text=get_serial_number_status(computer_info['serial_number']), fg='green' if get_serial_number_status(computer_info['serial_number']) == 'OK' else 'red') 请求了两次接口，暂时停用
    label_account_status.config(text='OK' if '不存在' not in label_account_value['text'] and datetime.datetime.strptime(label_account_value['text'].split('：')[1], '%Y-%m-%d %H:%M:%S') > datetime.datetime.now() else 'Fail', fg='green' if '不存在' not in label_account_value['text'] and datetime.datetime.strptime(label_account_value['text'].split('：')[1], '%Y-%m-%d %H:%M:%S') > datetime.datetime.now() else 'red')
    #获取公司域名
    get_domain_result = get_domain()
    label_domain_status.config(text='OK' if label_domain_value['text'] == get_domain_result else 'Fail', fg='green' if label_domain_value['text'] == get_domain_result else 'red')
    label_certificate_status.config(text='OK' if '未发现' in label_certificate_value['text'] or datetime.datetime.now() > datetime.datetime.strptime(label_certificate_value['text'].split('：')[1], '%Y-%m-%d %H:%M:%S') else 'Fail', fg='green' if '未发现' in label_certificate_value['text'] or datetime.datetime.now() > datetime.datetime.strptime(label_certificate_value['text'].split('：')[1], '%Y-%m-%d %H:%M:%S') else 'red')
    if label_serialnumber_status['text'] == 'OK' and label_account_status['text'] == 'OK' and label_domain_status['text'] == 'OK':
        button_request.config(state='normal')

#删除旧证书
def delete_old_certificate(username):
    command = 'get-childitem -path cert:\\currentuser\\my | where-object {{ $_.subject -like \'*{0}*\' -and $_.subject -like \'*OU*CN*O*C*\' }} | Remove-Item'.format(username)
    subprocess.run(['powershell', '-Command', command], shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

#弹窗提示
def messagebox_show():
    ret = messagebox.askyesno('提示','证书已经存在，是否继续申请？')
    if ret:
        try:
            requests.get(url, timeout=1)
            delete_old_certificate(computer_info['username'])
            request_certificate()
            messagebox_success()
        except requests.exceptions.ConnectionError:
            messagebox_network_fail()
            return

#弹窗提示网络连接失败
def messagebox_network_fail():
    messagebox.showinfo('提示','服务连接失败，请联系管理员')

#申请成功
def messagebox_success():
    messagebox.showinfo('提示','证书申请成功！')

#申请按钮
def request_button():
    if label_certificate_status['text'] == 'Fail':
        messagebox_show()
    else:
        try:
            requests.get(url, timeout=1)
            request_certificate()
            messagebox_success()
        except requests.exceptions.ConnectionError:
            messagebox_network_fail()
            return

#申请证书
def request_certificate():
    certificate_gen = create_certificate.certificate_generate()
    user_query = requests.get(url + '/user_query', params={'username': computer_info['username']})
    cert_csr = certificate_gen.create_csr(
        country_name='CN', 
        organization_name=domain, 
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
        URL=url + '/issue_certificate',
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
    
button_start = tk.Button(window, text='开始检查', font=('Microsoft YaHei', 15, 'bold'), fg='black', width=30, anchor='center', command=start_button)
button_start.grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky='nsew')

#序列号
label_serialnumber = tk.Label(window, text='序列号:', font=('Microsoft YaHei', 11, 'bold'), fg='black')
label_serialnumber.grid(row=1, column=0, sticky='w', padx=10)
label_serialnumber_value = tk.Label(window, font=('Microsoft YaHei', 11), fg='black')
label_serialnumber_value.grid(row=1, column=1, sticky='w')
label_serialnumber_status = tk.Label(window, font=('Microsoft YaHei', 11), fg='black', anchor='center')
label_serialnumber_status.grid(row=1, column=2, sticky='we')

#账号
label_account = tk.Label(window, text='账号:', font=('Microsoft YaHei', 11, 'bold'), fg='black')
label_account.grid(row=2, column=0, sticky='w', padx=10)
label_account_value = tk.Label(window, font=('Microsoft YaHei', 11), fg='black')
label_account_value.grid(row=2, column=1, sticky='w')
label_account_status = tk.Label(window, font=('Microsoft YaHei', 11), fg='black')
label_account_status.grid(row=2, column=2, sticky='we')

#加域
label_domain = tk.Label(window, text='加域情况：', font=('Microsoft YaHei', 11, 'bold'), fg='black')
label_domain.grid(row=3, column=0, sticky='w', padx=10)
label_domain_value = tk.Label(window, text='', font=('Microsoft YaHei', 11), fg='black')
label_domain_value.grid(row=3, column=1, sticky='w')
label_domain_status = tk.Label(window, text='', font=('Microsoft YaHei', 11), fg='black')
label_domain_status.grid(row=3, column=2, sticky='we')

#证书
label_certificate = tk.Label(window, text='证书情况：', font=('Microsoft YaHei', 11, 'bold'), fg='black')
label_certificate.grid(row=4, column=0, sticky='w', padx=10)
label_certificate_value = tk.Label(window, font=('Microsoft YaHei', 11), fg='black')
label_certificate_value.grid(row=4, column=1, sticky='w')
label_certificate_status = tk.Label(window, font=('Microsoft YaHei', 11), fg='black')
label_certificate_status.grid(row=4, column=2, sticky='we')

#申请按钮
button_request = tk.Button(window, text='申请证书', font=('Microsoft YaHei', 15, 'bold'), fg='black', state='disabled', command=request_button)
button_request.grid(row=0, column=2, padx=10, pady=10)

#作者与版本信息框架
footer_frame = tk.Frame(window)
footer_frame.grid(row=5, column=0, columnspan=4,sticky='se')

#设置作者信息
label_author = tk.Label(footer_frame, text='作者: yangwei@yangyuetong.com', font=('Arial', 9), fg='black')
label_author.pack(anchor='e')

#设置版本信息
label_version = tk.Label(footer_frame, text='版本: 1.0.0', font=('Arial', 9), fg='black')
label_version.pack(anchor='e')

window.mainloop()