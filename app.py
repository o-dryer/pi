import atexit
import csv
import logging
import os
import time
from csv import DictWriter
from datetime import timedelta, datetime
from sched import scheduler
from threading import Thread

import RPi.GPIO as GPIO
import adafruit_dht
import board
from flask import Flask

# TODO: Move to config file
PORT_DHT = board.D14
# main power switch 0, LOW on
PORT_MAIN = 2 # GPIO.BOARD 7
# PORT_MAIN = 27 # GPIO.BOARD 13
POWER_OFF = 1
POWER_ON = 0
# direction switch 0 -> open. 1 -> close
PORT_DIRECTION = 3 # GPIO.BOARD 11
DIRECTION_OPEN = 0
DIRECTION_CLOSE = 1
# max runtime in seconds
MAX_RUNTIME = 8
PROTOCOL_INTERVAL = 30
LOGLEVEL = logging.DEBUG
MAX_HUM = 60
MIN_TEMP = 21
AUTO_OPEN_LENGTH = 60
AUTO_OPEN_REST = 900
rest_until = datetime.now()

logging.basicConfig(format='%(asctime)s %(message)s', level=LOGLEVEL)
logging.debug('Start logging')

app = Flask(__name__)
GPIO.cleanup()
GPIO.setmode(GPIO.BCM)
GPIO.setup(PORT_MAIN, GPIO.OUT, initial=POWER_OFF)
GPIO.setup(PORT_DIRECTION, GPIO.OUT)
dht_device = adafruit_dht.DHT22(PORT_DHT)

def time_as_string():
    return datetime.now().strftime("%H:%M:%S")

state = {'time': time_as_string(),
             'state': 'unknown',
             'humidity': -1,
             'temperature': 100}

s = scheduler(time.time, time.sleep)
recorder = scheduler(time.time, time.sleep)


def should_open():
    global state
    logging.debug(f"Check conditions for state {state}")
    hum_too_high = state['humidity'] > MAX_HUM
    temperate_high_enough = state['temperature'] > MIN_TEMP
    logging.debug({
        "hum_too_high":hum_too_high,
        "temperate_high_enough":temperate_high_enough})
    return hum_too_high and temperate_high_enough


def get_state():
    global dht_device, state
    logging.debug('Get state')
    try:
        state['humidity'] = dht_device.humidity
        state['temperature'] = dht_device.temperature
        state['time'] = time_as_string()
    except Exception as e:
        logging.warning('Cannot read sensor data: %s', e)
    logging.debug(f'State returned {state}')

def do_events():
    global rest_until, state

    get_state()

    date = datetime.today().strftime("%y%m%d")
    filename = f'{date}.csv'
    file_exists = os.path.isfile(filename)
    with open(f'{date}.csv', 'a+') as file:
        fieldnames = ['time', 'state', 'humidity', 'temperature']
        writer: DictWriter = csv.DictWriter(file, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(state)
        file.close()
        if s.empty() and datetime.now() > rest_until:
            logging.debug("Que is empty. Checking window state.")
            if should_open():
                schedule_open(-1)
                t = Thread(target=run_queue)
                t.start()
                rest_until = datetime.now() + timedelta(seconds=AUTO_OPEN_REST)
        recorder.enter(PROTOCOL_INTERVAL, 1, do_events)
        Thread(target=run_recorder, daemon=False).start()


def run_recorder():
    recorder.run()

rec = Thread(target=do_events)
rec.start()

@app.route('/')
def info():
    global rest_until, state
    logging.debug('Opening main page')
    return f'Temperature {state["temperature"]}°C and ' \
           f'humidity {state["humidity"]}% ' \
           f'as of {state["time"]}.<br/>' \
           f'<a href="open/2">open window</a><br/>' \
           f'<a href="close/2">close window</a><br/>' \
           f'The window is currently {state["state"]} ' \
           f'and will not move before {rest_until}'

def stop_power():
    global state
    logging.debug('Stopping power')
    state['state'] =  f"stopped ({state['state']})"
    GPIO.output(PORT_MAIN, POWER_OFF)
    GPIO.output(PORT_DIRECTION, POWER_OFF)


def start_closing():
    global state
    logging.debug('Start closing')
    state['state'] = 'closing'
    GPIO.output(PORT_MAIN, POWER_ON)
    GPIO.output(PORT_DIRECTION, DIRECTION_CLOSE)


def start_opening():
    global state
    logging.debug('Start opening')
    state['state'] = 'opening'
    GPIO.output(PORT_MAIN, POWER_ON)
    GPIO.output(PORT_DIRECTION, DIRECTION_OPEN)


def check_open():
    if should_open():
        logging.debug('Keeping window open.')
        s.enter(AUTO_OPEN_LENGTH, 1, check_open)
    else:
        logging.debug('close window automatically')
        start_closing()
        s.enter(MAX_RUNTIME, 1, stop_power)


def schedule_open(sec):
    global state
    if state['state'] == 'shutdown':
        return
    list(map(s.cancel, s.queue))
    s.enter(0, 1, start_opening)
    s.enter(MAX_RUNTIME, 1, stop_power)
    if sec == -1:
        s.enter(AUTO_OPEN_LENGTH, 1, check_open)
        return
    s.enter(sec, 1, start_closing)
    s.enter(sec + MAX_RUNTIME, 1, stop_power)


def schedule_close(sec):
    global state
    if state['state'] == 'shutdown':
        return
    list(map(s.cancel, s.queue))
    s.enter(0, 1, start_closing)
    s.enter(MAX_RUNTIME, 1, stop_power)

def run_queue():
    s.run()


@atexit.register
def shutdown():
    global state
    logging.debug("shutting down")
    if state['state'] not in ['stopped (closing)', 'shutdown']:
        state['state'] = 'shutdown'
        logging.debug("closing window (shutdown)")
        start_closing()
        list(map(s.cancel, s.queue))
        s.enter(MAX_RUNTIME, 2, stop_power)
        s.run()


@app.route('/open/<int:minutes>')
def open_window(minutes: int = 2):
    global rest_until
    logging.debug('Opening window open page')
    schedule_open(minutes * 60)
    t = Thread(target=run_queue)
    t.start()
    close_time = (datetime.now() + timedelta(minutes=minutes))
    final_time = close_time.strftime("%H:%M:%S")
    rest_until = close_time + timedelta(seconds=AUTO_OPEN_REST)

    # TODO: Consider flask.Response(schedule_open(), mimetype='text/html')
    return f'Opening window until {final_time}.'


@app.route('/close/<int:minutes>')
def close_window(minutes: int = 2):
    global rest_until
    logging.debug('Close window manually.')
    list(map(s.cancel, s.queue))
    rest_until = datetime.now() + timedelta(seconds=minutes*60)
    schedule_close(minutes*60)
    t = Thread(target=run_queue)
    t.start()
    return f'Closing window at least util {rest_until}.'


if __name__ == '__main__':
    logging.debug('Running program as main')
    app.run(port=80, host='0.0.0.0')
