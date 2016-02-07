#! /usr/bin/env python2

"""
Script to catpure Raspberry Pi camera on GPIO change.
Resulting file is pushed to FTP server.
"""

import time
import datetime
import picamera
import ftplib

try:
    import RPi.GPIO as GPIO
except RuntimeError:
    print("Error importing RPi.GPIO! Requires su privileges.")

default_config_file = '/etc/capture/ftp_server.conf'
image_capture_path = '/tmp'

timestamp_format_string = "_%m%d%y_%H%M%S"

# Switch input is configured for GPIO 26 (pin 37), with a pullup enabled.
# The switch is active LOW 
switch_input = 37
switch_active = False
switch_state = True

def get_server_params(file):
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
    image_file = open(path + '/' + filename, 'r')
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
    params = get_server_params(default_config_file)

    # Open and configure camera module
    cam = picamera.PiCamera()
    configure_camera(cam)

    # Configure GPIO to monitor switch input with a callback
    configure_switch_gpio(switch_input)

    # Test interface
    print 'Testing capture and upload!'
    image_filename = gen_image_filename()
    cam.capture(image_capture_path + '/' + image_filename)
    open_server_and_upload_file(params, image_filename, image_capture_path)

    # Main loop
    while True:
        # Wait until switch flag is set
        if switch_active:
            # Switch is active, handle it
            if switch_state:
                # Switch is now closed
                print 'Mailbox was closed!'
            else:
                # Switch is open, capture the image and upload to the server
                print 'Mailbox was opened!'
                image_filename = gen_image_filename()
                cam.capture(image_capture_path + '/' + image_filename)
                open_server_and_upload_file(params, image_filename, image_capture_path)
            switch_active = False
        else:
            time.sleep(0.1)
    

if __name__ == '__main__':
    main()
