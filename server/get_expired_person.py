#! /usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import datetime
import json

DATABASE_PATH = 'config/database/database.db'


def main():
    now = datetime.datetime.now()
    future = now + datetime.timedelta(days=30)
    with sqlite3.connect(DATABASE_PATH) as f:
        cursor = f.cursor()
        cursor.execute(
            "SELECT username,displayname,mail,when_expired FROM user WHERE status = 'enabled' AND when_expired BETWEEN ? AND ?",
            (now.strftime('%Y-%m-%d %H:%M:%S'), future.strftime('%Y-%m-%d %H:%M:%S')),
        )
        query_result = cursor.fetchall()
    return json.dumps([{'username': i[0], 'displayname': i[1], 'mail': i[2], 'when_expired': i[3]} for i in query_result])


if __name__ == '__main__':
    print([list(d.values()) for d in json.loads(main())])