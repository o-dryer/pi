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
PORT_MAIN = 4
POWER_OFF = 1
POWER_ON = 0
# direction switch 0 -> open. 1 -> close
PORT_DIRECTION = 17
DIRECTION_OPEN = 0
DIRECTION_CLOSE = 1
# max runtime in seconds
MAX_RUNTIME = 8
PROTOCOL_INTERVAL = 30
LOGLEVEL = logging.DEBUG
MAX_HUM = 60
MIN_TEMP = 20
AUTO_OPEN_LENGTH = 600
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
window_state = 'unknown'
s = scheduler(time.time, time.sleep)
recorder = scheduler(time.time, time.sleep)


def write_log():
    global window_state, rest_until
    date = datetime.today().strftime("%y%m%d")
    filename = f'{date}.csv'
    file_exists = os.path.isfile(filename)
    with open(f'{date}.csv', 'a+') as file:
        fieldnames = ['time', 'state', 'humidity', 'temperature']
        writer: DictWriter = csv.DictWriter(file, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        state = get_state()
        writer.writerow(state)
        file.close()
        if s.empty():
            current_hour = datetime.now().hour
            if state['humidity'] > MAX_HUM and \
                    state['temperature'] > MIN_TEMP and \
                    datetime.now() > rest_until and \
                    19 != current_hour:
                schedule_open(AUTO_OPEN_LENGTH)
                t = Thread(target=run_queue)
                t.start()
                rest_until = (datetime.now() + timedelta(seconds=AUTO_OPEN_REST))
        recorder.enter(PROTOCOL_INTERVAL, 1, write_log)
        Thread(target=run_recorder, daemon=False).start()


def run_recorder():
    recorder.run()


def time_as_string():
    return datetime.now().strftime("%H:%M:%S")


rec = Thread(target=write_log)
rec.start()


def get_state():
    global dht_device
    logging.debug('Get state')
    state = {'time': time_as_string(),
             'state': window_state,
             'humidity': -1,
             'temperature': -100}
    try:
        state['humidity'] = dht_device.humidity
        state['temperature'] = dht_device.temperature
    except Exception as e:
        logging.warning('Cannot read sensor data: %s', e)
    logging.debug('State returned')
    return state


@app.route('/')
def info():
    logging.debug('Opening main page')
    state = get_state()

    return f'Temperature {state["temperature"]}°C and ' \
           f'humidity {state["humidity"]}% ' \
           f'as of {state["time"]}.<br/>' \
           f'<a href="open/2">open window</a><br/>' \
           f'<a href="close">close window</a>'


def stop_power():
    global window_state
    logging.debug('Stopping power')
    window_state = f"stopped ({window_state})"
    GPIO.output(PORT_MAIN, POWER_OFF)
    GPIO.output(PORT_DIRECTION, POWER_OFF)


def start_closing():
    global window_state
    logging.debug('Start closing')
    window_state = 'closing'
    GPIO.output(PORT_MAIN, POWER_ON)
    GPIO.output(PORT_DIRECTION, DIRECTION_CLOSE)


def start_opening():
    global window_state
    logging.debug('Start opening')
    window_state = 'opening'
    GPIO.output(PORT_MAIN, POWER_ON)
    GPIO.output(PORT_DIRECTION, DIRECTION_OPEN)


def schedule_open(sec):
    global window_state
    if window_state == 'shutdown':
        return
    list(map(s.cancel, s.queue))
    s.enter(0, 1, start_opening)
    s.enter(MAX_RUNTIME, 1, stop_power)
    s.enter(sec, 1, start_closing)
    s.enter(sec + MAX_RUNTIME, 1, stop_power)


def run_queue():
    s.run()


@atexit.register
def shutdown():
    global window_state
    logging.debug("shutting down")
    if window_state not in ['stopped (closing)', 'shutdown']:
        window_state = 'shutdown'
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

@app.route('/close')
def close_window():
    global rest_until
    logging.debug('Close window manually.')
    list(map(s.cancel, s.queue))
    rest_until = datetime.now() + timedelta(seconds=AUTO_OPEN_REST)
    start_closing()
    return f'Closing window at least util {rest_until}.'


if __name__ == '__main__':
    logging.debug('Running program as main')
    app.run(port=80, host='0.0.0.0')
