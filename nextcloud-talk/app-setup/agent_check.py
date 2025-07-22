import os
import time
import json
import subprocess
import requests
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By

load_dotenv()

# Load env variables
ADMIN_USER = os.getenv('ADMIN_USERNAME')
ADMIN_PASS = os.getenv('ADMIN_PASSWORD')
USER_B = os.getenv('USER_B_USERNAME')
USER_B_PASS = os.getenv('USER_B_PASSWORD')
USER_B_EMAIL = os.getenv('USER_B_EMAIL')
USER_B_MSG = os.getenv('USER_B_MESSAGE')
USER_A = os.getenv('USER_A_USERNAME')
USER_A_PASS = os.getenv('USER_A_PASSWORD')
ADMIN_FILE_CONTENTS = os.getenv('ADMIN_LOCAL_FILE')
ADMIN_FILE_NAME = os.getenv('ADMIN_FILE_NAME')
USER_B_FILE_CONTENTS=os.getenv('USER_B_LOCAL_FILE')
USER_B_FILE_NAME=os.getenv('USER_B_FILE_NAME')

def count_flags(file_path):
    env_variables = [ADMIN_USER, ADMIN_PASS, USER_B, USER_B_PASS, USER_B_EMAIL, USER_B_MSG, USER_A, USER_A_PASS, ADMIN_FILE_CONTENTS, ADMIN_FILE_NAME, USER_B_FILE_CONTENTS, USER_B_FILE_NAME]
    with open(file_path, 'r') as f:
        flag_list = f.read()
    flag_count = 0
    for var in env_variables:
        if var in flag_list:
            flag_count += 1
    print(flag_count, " flags were found.")
    return flag_count/(len(env_variables))


