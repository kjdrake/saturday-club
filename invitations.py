"""Invitation email delivery through SES using the EC2 instance role."""
import os
import re
import urllib.parse

def public_url():
    base = os.getenv('APP_URL', '').rstrip('/')
    url = urllib.parse.urlparse(base)
    if url.scheme != 'https' or not url.netloc or url.path or url.query or url.fragment or url.username:
        return None
    return base

def valid_email(email):
    return len(email) <= 254 and bool(re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", email))

def ready():
    return bool(public_url() and valid_email(os.getenv('SES_FROM_EMAIL', '')))

def send_message(recipient, subject, text):
    # The SDK uses short-lived instance-role credentials, never browser/GitHub keys.
    import boto3
    from botocore.config import Config
    client = boto3.client('sesv2', region_name=os.getenv('AWS_REGION', 'us-east-1'), config=Config(connect_timeout=5, read_timeout=10, retries={'total_max_attempts':1}))
    response = client.send_email(
        FromEmailAddress=os.environ['SES_FROM_EMAIL'], Destination={'ToAddresses':[recipient]},
        Content={'Simple':{
            'Subject':{'Data':subject,'Charset':'UTF-8'},
            'Body':{'Text':{'Data':text,'Charset':'UTF-8'}},
        }},
    )
    return response['MessageId']

def send_email(recipient, name, link):
    return send_message(recipient, 'Your invitation to Saturday Club', f"Hi {name},\n\nYou're invited to Saturday Club by 4th & Soul. Join our college football pick'em league:\n\n{link}\n\nThis invitation can be used once and expires in seven days. Create an account with your email and password, or use Google or Facebook when available.\n\nSee you Saturday!")

def send_password_reset(recipient, name, link):
    return send_message(recipient, 'Reset your Saturday Club password', f"Hi {name},\n\nUse this link to choose a new Saturday Club password:\n\n{link}\n\nThis link expires in 30 minutes and works once. Your existing password is unchanged until you submit a new one. If you did not request this, ignore this email. Never share this link or your password.\n\nSaturday Club by 4th & Soul")
