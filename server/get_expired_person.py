#! /bin/env/python3
#! -*- coding: utf-8 -*-

import sqlite3
import datetime
import json

with sqlite3.connect('config/database/database.db') as f:
    cursor = f.cursor()
    cursor.execute("SELECT username,displayname,mail,when_expired FROM user WHERE status = 'enabled' AND when_expired < ?", ((datetime.datetime.now() + datetime.timedelta(days=90)).strftime('%Y-%m-%d %H:%M:%S'),))
    query_result = cursor.fetchall()

def main():
    return json.dumps([{'username': i[0], 'displayname': i[1], 'mail': i[2], 'when_expired': i[3]} for i in query_result])

if __name__ == '__main__':
    
    print([list(d.values()) for d in json.loads(main())])