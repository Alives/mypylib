#!/usr/bin/python3

import json
import logging
import os
import requests
import smtplib
import socket
import sys
import time


from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


class InfoFilter(logging.Filter):
  """Filter the StreamHandler output for typical stdout levels."""
  def filter(self, rec):
    return rec.levelno in (logging.DEBUG, logging.INFO)


# https://www.twilio.com/docs/voice/api/call-resource
def call(cred_file, num_to, num_from='', msg='trial'):
  URL = 'https://api.twilio.com/2010-04-01/Accounts/%s/Calls.json'
  with open(cred_file) as f:
    creds = json.load(f)
  if not num_from:
    num_from = creds['from']
  data = {
      'From': num_from,
      'To': num_to,
      'Twiml': f'<Response><Say>{msg}</Say></Response>',
  }
  requests.post(URL % creds['sid'],
                auth=requests.auth.HTTPBasicAuth(creds['sid'], creds['token']),
                data=data)


def get_statefile(extension='txt'):
  splits = os.path.realpath(sys.argv[0]).split('/')
  filename = f'state_{splits[-1].rsplit(".", 1)[0]}.{extension}'
  return '/'.join(splits[:-1] + [filename])


def get_url(url, headers={}, attempts=5):
  if not headers:
    headers = {'User-Agent': user_agent()}
  logging.info('Loading %s', url)
  for attempt in range(attempts+1):
    try:
      response = requests.get(url, headers=headers, timeout=2)
      return response.text.strip()
    except requests.exceptions.ConnectionError:
      logging.error('Connection Error for %s.', url)
      time.sleep(attempt*2)
    except requests.exceptions.ReadTimeout:
      logging.error('URL read timeout for %s.', url)
  logging.error('Connection retries exhausted for %s.', url)
  return ''


def humanize(n: float, suffix: str='bps'):
    n = round(n)
    for unit in ' KMG':
      if abs(n) < 1000:
        return '%d %s%s' % (n, unit, suffix)
      n /= 1000


def send_email(from_addr, to_addrs, subject, body, fixedwidth=False,
               dest='10.0.0.2:25'):
  msg = MIMEMultipart()
  msg['From'] = from_addr
  msg['To'] = to_addrs
  msg['Subject'] = subject
  logging.info('Subject: %s', repr(msg['Subject']))
  logging.info('From: %s', msg['From'])
  logging.info('To: %s', msg['To'])
  logging.info('Body length: %d', len(body))
  envelope_to = [x.strip() for x in msg['To'].split(',')]
  if fixedwidth:
    body = f'<pre>{body}</pre>'
  msg.attach(MIMEText(body, 'html'))
  try:
    smtp = smtplib.SMTP('10.0.0.2:25')
    result = smtp.sendmail(msg['From'], envelope_to, msg.as_string())
  except:
    logging.error('Sending email failed.')
    return
  finally:
    smtp.close()
  logging.info('Success.')
  if result:
    logging.error(repr(result))


def setup_logging(logfile: str, debug=False, fileinfo=True, lineno=True):
  lineno_str = ':%(lineno)-3s'
  fileinfo_str = f' %(filename)s'
  if not fileinfo:
    fileinfo_str = ''
  if not lineno_str:
    lineno_str = ''
  log_formatter = logging.Formatter(
      f'%(levelname).1s%(asctime)s{fileinfo_str}{lineno_str}]  %(message)s',
      datefmt='%Y-%m-%d_%H:%M:%S')
  logger = logging.getLogger()
  logger.setLevel(logging.INFO)
  if debug:
    logger.setLevel(logging.DEBUG)

  # Log eveything to a file.
  file_handler = logging.FileHandler(logfile)
  file_handler.setFormatter(log_formatter)

  # Print stdout levels to stdout.
  stdout_handler = logging.StreamHandler(sys.stdout)
  stdout_handler.setFormatter(log_formatter)
  stdout_handler.addFilter(InfoFilter())

  # Print stderr levels to stderr (to be emailed via the cron output).
  stderr_handler = logging.StreamHandler()
  stderr_handler.setFormatter(log_formatter)
  stderr_handler.setLevel(logging.WARNING)

  logger.addHandler(file_handler)
  logger.addHandler(stdout_handler)
  logger.addHandler(stderr_handler)


def telegram(creds: str, msg: str):
  with open(creds) as f:
    data = json.load(f)
  bot_id = data['bot_id']
  chat_id = data['chat_id']
  requests.post('https://api.telegram.org/bot%s/sendMessage' % bot_id,
      params = {
        'chat_id': chat_id,
        'disable_web_page_preview': True,
        'text': msg})


def user_agent():
  with open('/opt/user_agent.txt') as f:
    return f.read().strip()


def write_graphite_entries(entries: list, port: int=2003, server: str='10.0.02',
                           verbose: bool=False):
  datafile = '/opt/graphite_data.txt'
  try:
    with open(datafile) as f:
      prev_entries = f.read().splitlines()
  except:
    prev_entries = []
  if prev_entries:
    logging.warning('Previously unwritten graphite data is %d entries long.',
                    len(prev_entries))
  sock = socket.socket()
  sock.settimeout(5)
  try:
    sock.connect((server, port))
    connected = True
  except socket.error as error:
    connected = False
    logging.error('ERROR couldnt connect to graphite: %s', error)
    logging.error('Queueing data for later writing...')
  if connected:
    msg = bytes('\n'.join(prev_entries + entries) + '\n', 'ascii')
    sock.sendall(msg)
    if verbose:
      for entry in entries:
        logging.info(entry)
    entries = []
  if connected:
    sock.close()
  with open(datafile, 'w') as f:
    f.write('\n'.join(entries))


def write_graphite(data: list, prefix: str='', port: int=2003,
                   server: str='10.0.0.2', verbose: bool=False):
  now = int(time.mktime(time.localtime()))
  for name, value in data:
    if prefix:
      metric = '%s.%s' % (prefix, name)
    else:
      metric = name
    entries.append('%s %s %d.' % (metric, value, now))
  write_graphite_entries(entries, port, server, verbose)
