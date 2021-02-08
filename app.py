from flask import Flask
import datetime
import board
import adafruit_dht
import RPi.GPIO as GPIO
import time
import logging
from sched import scheduler
from threading import Thread

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
LOGLEVEL = logging.DEBUG

logging.basicConfig(format='%(asctime)s %(message)s', level=LOGLEVEL)
logging.debug('Start logging')

app = Flask(__name__)
dht_device = adafruit_dht.DHT22(PORT_DHT)
GPIO.cleanup()
GPIO.setmode(GPIO.BCM)
GPIO.setup(PORT_MAIN, GPIO.OUT, initial=POWER_OFF)
GPIO.setup(PORT_DIRECTION, GPIO.OUT)
s = scheduler(time.time, time.sleep)


@app.route('/')
def info():
    logging.debug('Opening main page')
    temperature = dht_device.temperature
    humidity = dht_device.humidity
    current_time = datetime.datetime.now().strftime("%H:%M:%S")

    return f'Temperature {temperature}°C and humidity {humidity}% as of {current_time}.<br/>' \
           f'<a href="open/2">open window</a>'


def stop_power():
    logging.debug('Stopping power')
    GPIO.output(PORT_MAIN, POWER_OFF)
    GPIO.output(PORT_DIRECTION, POWER_OFF)


def start_closing():
    logging.debug('Start closing')
    GPIO.output(PORT_MAIN, POWER_ON)
    GPIO.output(PORT_DIRECTION, DIRECTION_CLOSE)


def start_opening():
    logging.debug('Start opening')
    GPIO.output(PORT_MAIN, POWER_ON)
    GPIO.output(PORT_DIRECTION, DIRECTION_OPEN)


def schedule_open(sec):
    list(map(s.cancel, s.queue))
    s.enter(0, 1, start_opening)
    s.enter(MAX_RUNTIME, 1, stop_power)
    s.enter(sec, 1, start_closing)
    s.enter(sec + MAX_RUNTIME, 1, stop_power)


def run_queue():
    s.run()


@app.route('/open/<int:minutes>')
def open_window(minutes: int = 2):
    logging.debug('Opening window open page')
    schedule_open(minutes * 60)
    t = Thread(target=run_queue)
    t.start()
    final_time = (datetime.datetime.now() + datetime.timedelta(minutes=minutes)).strftime("%H:%M:%S")
    # TODO: Consider flask.Response(schedule_open(), mimetype='text/html')
    return f'Opening window until {final_time}.'


if __name__ == '__main__':
    logging.debug('Running program as main')
    app.run(port=80, host='0.0.0.0')
