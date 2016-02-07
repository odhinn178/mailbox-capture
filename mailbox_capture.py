#! /usr/bin/env python2

"""
Script to catpure Raspberry Pi camera on GPIO change.
Resulting file is pushed to FTP server.
"""

import time
import datetime
import os

import picamera
import ftplib

import httplib2
from apiclient import discovery
from apiclient import errors
import oauth2client
from oauth2client import client
from oauth2client import tools

from email.MIMEMultipart import MIMEMultipart
from email.MIMEBase import MIMEBase
from email.MIMEText import MIMEText
from email.MIMEImage import MIMEImage
import mimetypes
import base64

try:
    import RPi.GPIO as GPIO
except RuntimeError:
    print("Error importing RPi.GPIO! Requires su privileges.")

try:
    import argparse
    flags = argparse.ArgumentParser(parents=[tools.argparser]).parse_args()
except ImportError:
    flags = None

default_config_file = '/etc/capture/ftp_server.conf'
gmail_message_data = '/etc/capture/gmail_header.conf'
image_capture_path = '/tmp'

timestamp_format_string = "_%m%d%y_%H%M%S"

# Switch input is configured for GPIO 26 (pin 37), with a pullup enabled.
# The switch is active LOW 
switch_input = 37
switch_active = False
switch_state = True

SCOPES = 'https://www.googleapis.com/auth/gmail.send'
CLIENT_SECRET_FILE = 'client_secret.json'
APPLICATION_NAME = 'Raspberry PI Mailbox Capture'

mb_open_subject = 'Mailbox was opened!'
mb_closed_subject = 'Mailbox was closed!'

def get_params(file):
    """
    Opens and parses the config file, returning a dict of params
    """
    try:
        config_file = open(file, 'r')
    except IOError:
        print "Cannot open ", file

    config_params = [line.strip().split('=') for line in config_file]
    config_file.close()

    params = {key: value for (key, value) in config_params}
    return params


def open_server_and_upload_file(params, filename, path):
    """
    Opens the FTP server and uploads the image file
    """
    try:
        # Open the server connection
        ftp = ftplib.FTP_TLS(params['server'])
        ftp.connect(params['server'], int(params['port']))
        ftp.login(params['username'], params['password'])
        ftp.prot_p()
    except:
        print 'FTP Error! Could not open server...'

    # Set upload path
    ftp.cwd(params['path'])

    # Open the file and store it on the FTP server
    image_path = os.path.join(path, filename)
    image_file = open(image_path, 'r')
    try:
        ftp.storbinary('STOR ' + filename, image_file)
    except:
        print 'Could not upload image file to FTP server!'
    image_file.close()
    ftp.close()


def configure_camera(camera):
    """
    Opens and configures the camera module, returning the handle to the camera
    """
    camera.hflip = True
    camera.vflip = True
    camera.brightness = 55
    camera.exposure_mode = 'night'
    camera.exposure_compensation = 2
    

def gen_image_filename():
    """ 
    Generate the filename for the image output file
    """
    now = datetime.datetime.now()
    timestamp_str = now.strftime(timestamp_format_string)
    filename = "cam_capture" + timestamp_str + ".jpg"
    return filename


def get_credentials():
    """
    Gets valid user credentials from storage.

    If nothing has been stored, or if the stored credentials are invalid,
    the OAuth2 flow is completed to obtain the new credentials.

    Returns:
        Credentials, the obtained credential.
    """
    home_dir = os.path.expanduser('~')
    credential_dir = os.path.join(home_dir, '.credentials')
    if not os.path.exists(credential_dir):
        os.makedirs(credential_dir)
    credential_path = os.path.join(credential_dir,
                                   'rpi-mailbox-capture.json')

    store = oauth2client.file.Storage(credential_path)
    credentials = store.get()
    if not credentials or credentials.invalid:
        flow = client.flow_from_clientsecrets(CLIENT_SECRET_FILE, SCOPES)
        flow.user_agent = APPLICATION_NAME
        if flags:
            credentials = tools.run_flow(flow, store, flags)
        else: # Needed only for compatibility with Python 2.6
            credentials = tools.run(flow, store)
        print 'Storing credentials to ' + credential_path
    return credentials


def create_message_with_attachment(params, subject, message_text, file_dir, filename):
    """
    Create the message with an attachment
    """
    # create a message to send
    message = MIMEMultipart()
    message['to'] = params['to']
    message['from'] = params['sender']
    message['subject'] = subject
    
    msg = MIMEText(message_text)
    message.attach(msg)

    path = os.path.join(file_dir, filename)
    content_type, encoding = mimetypes.guess_type(path)
    main_type, sub_type = content_type.split('/', 1)

    fp = open(path, 'rb')
    msg = MIMEImage(fp.read(), _subtype=sub_type)
    fp.close()

    msg.add_header('Content-Disposition', 'attachment', filename=filename)
    message.attach(msg)

    return {'raw': base64.urlsafe_b64encode(message.as_string())}


def send_message(service, user_id, message):
    """
    Sends a message via the Gmail API
    """
    try:
        message = (service.users().messages().send(userId=user_id, body=message).execute())
        print 'Message ID: %s' % message['id']
        return message
    except errors.HttpError, error:
        print 'An error occurred: %s' % error


def configure_switch_gpio(switch):
    """
    Configures the GPIO switch input and registers the event callback
    """
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(switch, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.add_event_detect(switch, GPIO.BOTH, callback=switch_active_callback, bouncetime=200)


def switch_active_callback():
    """
    The threaded callback function for the switch active detection
    """
    global switch_active
    switch_active = True
    print 'Switch state was changed!'
    if GPIO.input(switch_input):
        print 'Switch was closed!'
        switch_state = True
    else:
        print 'Switch was opened!'
        switch_state = False


def main():
    global switch_active

    # Import server and credentials from external file
    ftp_params = get_params(default_config_file)

    # Open and configure camera module
    cam = picamera.PiCamera()
    configure_camera(cam)

    # Configure GPIO to monitor switch input with a callback
    configure_switch_gpio(switch_input)

    # Get Gmail API credentials
    credentials = get_credentials();
    http = credentials.authorize(httplib2.Http())
    service = discovery.build('gmail', 'v1', http=http)

    # Test interface
    print 'Testing capture and upload!'
    image_filename = gen_image_filename()
    image_path = os.path.join(image_capture_path, image_filename)
    cam.capture(image_path)
    open_server_and_upload_file(ftp_params, image_filename, image_capture_path)

    # Create and send a test email with the captured image
    mail_params = get_params(gmail_message_data)
    msg = create_message_with_attachment(mail_params, mb_open_subject, 'Image file attached\n', 
                                            image_capture_path, image_filename)
    resp = send_message(service, 'me', msg)
    print resp

    # Main loop
    while True:
        # Wait until switch flag is set
        if switch_active:
            # Switch is active, handle it
            if switch_state:
                # Switch is now closed
                print mb_closed_subject
            else:
                # Switch is open, capture the image and upload to the server
                print mb_open_subject
                image_filename = gen_image_filename()
                image_path = os.path.join(image_capture_path, image_filename)
                cam.capture(image_path)
                open_server_and_upload_file(ftp_params, image_filename, image_capture_path)
            switch_active = False
        else:
            time.sleep(0.1)
    

if __name__ == '__main__':
    main()
