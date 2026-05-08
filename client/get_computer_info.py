#! /usr/env/python3
#! -*- coding: utf-8 -*-

import os
import subprocess
import platform

class computer_info:
    def __init__(self):
        self.info = {}

    def __str__(self):
        return str(self.info)

    def get_computer_info(self):
        self.info['hostname'] = self.get_hostname()
        self.info['ip_address'] = self.get_ip_address()
        self.info['serial_number'] = self.get_serial_number()
        self.info['domain'] = self.get_domain()
        self.info['username'] = os.getlogin()
        self.info['display_username'] = self.get_display_username()
        self.info['os'] = platform.platform()
        return self.info

    def get_ip_address(self):
        result = subprocess.check_output(['powershell', '-Command', 'Get-WmiObject Win32_NetworkAdapterConfiguration | Where-Object {$_.IPEnabled -eq $true -and $_.DefaultIPGateway -and $_.DefaultIPGateway.Length -gt 0} | Select-Object -ExpandProperty IPAddress'], shell=True)
        ip_address = result.decode('utf-8').strip().split()
        return ip_address

    def get_serial_number(self):
        result = subprocess.check_output(['powershell', '-Command', 'Get-WmiObject Win32_BIOS | Select-Object -ExpandProperty SerialNumber'], shell=True)
        serial_number = result.decode('utf-8').strip()
        return serial_number

    def get_domain(self):
        result = subprocess.check_output(['powershell', '-Command', 'Get-WmiObject Win32_ComputerSystem | Select-Object -ExpandProperty Domain'], shell=True)
        domain = result.decode('utf-8').strip()
        return domain
        
    def get_hostname(self):
        result = subprocess.check_output(['powershell', '-Command', 'Get-WmiObject Win32_ComputerSystem | Select-Object -ExpandProperty Name'], shell=True)
        hostname = result.decode('utf-8').strip()
        return hostname
    
    def get_display_username(self):
        result = subprocess.check_output(['powershell', '-Command', 'Get-WmiObject win32_useraccount | where-object {$_.Name -like \'' + os.getlogin() + '\'} | Select-object -Expandproperty Fullname'], shell=True)
        display_username = result.decode('utf-8').strip()
        return display_username


if __name__ == "__main__":
    computer = computer_info()
    info = computer.get_computer_info()
    # request_data = {'hostname': info['hostname'], 'ip_address': info['ip_address'], 'serial_number': info['serial_number'], 'domain': info['domain'], 'username': info['username'], 'display_username': info['display_username'], 'os': info['os']}
    # r = requests.post(url, json=request_data)
    # print(r.status_code)
    # print(r.text)
    print(info)
