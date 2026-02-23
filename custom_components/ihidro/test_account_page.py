#!/usr/bin/env python3
"""Test if we can get CSRF token from account.aspx without browser."""

import requests
import re
from bs4 import BeautifulSoup
import logging

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger(__name__)

USERNAME = "emanuelbesliu"
PASSWORD = "E351b41598@"

session = requests.Session()
session.verify = False

try:
    # Step 1: Navigate to default.aspx to get initial page
    _LOGGER.info("Getting initial page...")
    resp = session.get('https://ihidro.ro/portal/default.aspx', timeout=30)
    resp.raise_for_status()
    
    # Extract __VIEWSTATE and other form fields
    soup = BeautifulSoup(resp.text, 'html.parser')
    viewstate = soup.find('input', {'id': '__VIEWSTATE'})['value']
    viewstate_gen = soup.find('input', {'id': '__VIEWSTATEGENERATOR'})['value']
    event_validation = soup.find('input', {'id': '__EVENTVALIDATION'})['value']
    
    _LOGGER.info("Extracted form fields for login")
    
    # Step 2: Submit login form
    _LOGGER.info("Submitting login form...")
    login_data = {
        '__VIEWSTATE': viewstate,
        '__VIEWSTATEGENERATOR': viewstate_gen,
        '__EVENTVALIDATION': event_validation,
        'txtLogin': USERNAME,
        'txtpwd': PASSWORD,
        'btnlogin': 'Conectare'
    }
    
    resp = session.post(
        'https://ihidro.ro/portal/default.aspx',
        data=login_data,
        timeout=30,
        allow_redirects=True
    )
    resp.raise_for_status()
    
    _LOGGER.info(f"Login response: {resp.status_code}, URL: {resp.url}")
    
    # Step 3: Try to access account.aspx
    _LOGGER.info("Accessing account.aspx...")
    resp = session.get('https://ihidro.ro/portal/account.aspx', timeout=30)
    resp.raise_for_status()
    
    # Extract CSRF token
    soup = BeautifulSoup(resp.text, 'html.parser')
    token_field = soup.find('input', {'id': 'hdnCSRFToken'})
    
    if token_field and token_field.get('value'):
        token = token_field['value']
        _LOGGER.info(f"\n✅ SUCCESS! Got CSRF token: {token[:30]}...")
        _LOGGER.info(f"Token length: {len(token)}")
        
        # Test the token with an API call
        _LOGGER.info("\nTesting token with GetAllPODBind API...")
        headers = {
            'Content-Type': 'application/json',
            'csrftoken': token,
            'isajax': '1'
        }
        
        api_resp = session.post(
            'https://ihidro.ro/portal/IndexHistory.aspx/GetAllPODBind',
            json={},
            headers=headers,
            timeout=30
        )
        _LOGGER.info(f"API Response: {api_resp.status_code}")
        _LOGGER.info(f"API Data: {api_resp.json()}")
        
    else:
        _LOGGER.error("❌ Token field not found or empty!")
        _LOGGER.info(f"Page title: {soup.find('title').text if soup.find('title') else 'No title'}")
        
        # Check if we got redirected to login
        if 'txtLogin' in resp.text:
            _LOGGER.error("We were redirected back to login page!")

except Exception as e:
    _LOGGER.error(f"Error: {e}", exc_info=True)
