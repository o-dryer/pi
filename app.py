from flask import Flask
from datetime import datetime
import board
import adafruit_dht

# TODO: Make ports configurable
dht_device = adafruit_dht.DHT22(board.D14)

app = Flask(__name__)


@app.route('/')
def hello_world():
    temperature = dht_device.temperature
    humidity = dht_device.humidity 
    current_time = datetime.now().strftime("%H:%M:%S")

    return f'Temperature {temperature}°C and humidity {humidity}% as of {current_time}.'


if __name__ == '__main__':
    app.run(port=80, host='0.0.0.0')
