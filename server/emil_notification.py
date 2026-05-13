#! /usr/bin/python3
#! /*-* coding: utf-8 -*-

import smtplib
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.base import MIMEBase
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.utils import parseaddr, formataddr
from email import encoders
import time
import datetime as dt
import json
import sqlite3

def _format_addr(s:str):
    name, addr = parseaddr(s)
    return formataddr((Header(name, 'utf-8').encode(), addr))

def main(expired_persons: list):
    with sqlite3.connect('config/database/database.db') as f:
        cursor = f.cursor()
        cursor.execute("SELECT company_name,common_name,url,mail_id,mail_pwd,mail_server,mail_server_port FROM configuration")
        query_result = cursor.fetchall()

    url = query_result[0][2]
    mail_id = query_result[0][3]
    mail_pwd = query_result[0][4]
    mail_server = query_result[0][5]
    mail_server_port = query_result[0][6]
    company_name = query_result[0][0]
    for json_in in expired_persons:
        from_addr = mail_id
        to_addr = json_in['mail']
        subject = '【系统提醒】域账号密码即将到期通知'

        msg = MIMEMultipart('related')
        msg['From'] = _format_addr('证书管理系统 <%s>' % from_addr)
        msg['To'] = _format_addr('%s <%s>' % (json_in['displayname'], to_addr))
        msg['Subject'] = Header(subject, 'utf-8').encode()

        html =f""" 
                <html>
                    <body>
                        <h3>尊敬的{json_in["displayname"]}:</h3>
                            <p>&nbsp;&nbsp;&nbsp;&nbsp;您好，</p>
                            <p>&nbsp;&nbsp;&nbsp;&nbsp;您的账号 <b>{json_in["username"]}</b> 将于 <span style="color: red; font-size: 16px" >{json_in["when_expired"]}</span> 密码过期，请及时到 <a href="{url}">{url}</a> 更新密码。</p>
                            <p>&nbsp;&nbsp;&nbsp;&nbsp;请提前修改密码，以免耽误您的工作，如遭遇问题请及时联系。</p>
                            <br><br>
                            <p style="text-align: right;">{company_name} IT部门</p>
                            <p style="text-align: right;">{dt.datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
                            <img src="cid:0" alt="logo" align="right">
                    </body>
                </html> """
        
        msg.attach(MIMEText(html, 'html', 'utf-8'))
        
        with open('config/logo.png', 'rb') as f:
            mime = MIMEBase('image', 'png', filename='logo.png')
            mime.add_header('Content-Disposition', 'attachment', filename='logo.png')
            mime.add_header('Content-ID', '<0>')
            mime.add_header('X-Attachment-Id', '0')
            mime.set_payload(f.read())
            encoders.encode_base64(mime)
            msg.attach(mime)

        server = smtplib.SMTP_SSL(mail_server, mail_server_port)
        server.login(mail_id, mail_pwd)
        server.sendmail(mail_id, json_in['mail'], msg.as_string())
        print(f'正在向{json_in["displayname"]} <{json_in["mail"]}>发送邮件')
        server.quit()
        print(f'已向{json_in["displayname"]} <{json_in["mail"]}>发送邮件')
        with sqlite3.connect('config/database/database.db') as f:
            cursor = f.cursor()
            cursor.execute("INSERT INTO log (timestamp, action, username, details) VALUES (datetime('now', +'8 hours'), ?, ?, ?)", 
                      ('emil_notification', 
                       json_in['username'], 
                       '已向' + json_in['displayname'] + '<' + json_in['mail'] + '>发送修改密码提醒邮件'))
        time.sleep(3)

if __name__ == '__main__':
    from server.get_expired_person import main as get_expired_person

    expired_persons = json.loads(get_expired_person())
    main(expired_persons)