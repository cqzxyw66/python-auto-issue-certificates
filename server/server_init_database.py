#! /bin/env/python3
#! -*- coding: utf-8 -*-

import sqlite3

def init_database():
    conn = sqlite3.connect('config/database/database.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS request_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp timestamp,
                        hostname TEXT,
                        ip_address TEXT,
                        serial_number TEXT,
                        domain TEXT,
                        username TEXT,
                        display_username TEXT,
                        os TEXT,
                        csr TEXT,
                        private_key TEXT,
                        certificate TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS configuration (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        company_name TEXT not null,
                        company_logo BLOB,
                        common_name TEXT not null,
                        logo BLOB,
                        url TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        userid INTEGER,
                        username TEXT UNIQUE not null,
                        password hash TEXT,
                        display_name TEXT,
                        role TEXT,
                        email TEXT,
                        state NUMERIC,
                        phone TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp timestamp,
                        action TEXT,
                        username TEXT,
                        details TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS serial_number (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        serial_number TEXT UNIQUE)''')
    cursor.close()
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_database()