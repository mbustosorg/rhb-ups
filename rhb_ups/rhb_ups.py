"""
    Copyright (C) 2024 Mauricio Bustos (m@bustos.org)
    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.
    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.
    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import argparse
import asyncio
import datetime
import logging
from logging.handlers import RotatingFileHandler
from subprocess import call

from INA219 import INA219
import RPi.GPIO as GPIO
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer

FORMAT = "%(asctime)-15s|%(module)s|%(lineno)d|%(message)s"
logging.basicConfig(format=FORMAT)
logger = logging.getLogger(__file__)
logger.setLevel(logging.INFO)

FILE_HANDLER = RotatingFileHandler("rhb-ups.log", maxBytes=40000, backupCount=5)
FILE_HANDLER.setLevel(logging.INFO)
FILE_HANDLER.setFormatter(FORMAT)
logger.addHandler(FILE_HANDLER)

last_change = 0

GPIO.setmode(GPIO.BOARD)
LIGHT_RELAY_PIN = 22
GPIO.setup(LIGHT_RELAY_PIN, GPIO.OUT)
light_on = False
light_on_time = None


def handle_light(unused_addr, args):
    """ Handle the update from the pressure sensor """
    global light_on, light_on_time
    try:
        logger.info(f'[{args}]')
        light_on = not light_on
        light_on_time = datetime.datetime.now()
    except ValueError as e:
        logger.error(e)


async def loop():
    global light_on, light_on_time
    car_started_for_night = False
    worklight_on = False
    GPIO.output(LIGHT_RELAY_PIN, 0)
    ina219 = INA219(addr=0x43)
    while True:
        time = datetime.datetime.now()
        car_running = ina219.getCurrent_mA() >= 0.0
        battery_level = ina219.percentage()
        if not car_running and battery_level < 50.0:
            logger.info("Battery level too low and car not running, shutting down...")
            call("sudo shutdown -h now", shell=True)
        if light_on:
            GPIO.output(LIGHT_RELAY_PIN, 1)
            if (time - light_on_time).total_seconds() / 60.0 > 10:
                light_on = False
                light_on_time = None
                GPIO.output(LIGHT_RELAY_PIN, 0)
                logger.info("Shutting down light after 10 minutes")
                continue
        if 7 < time.hour < 19:
            if worklight_on:
                logger.info("Shutting down for daytime")
                worklight_on = False
            GPIO.output(LIGHT_RELAY_PIN, 0)
            continue
        if not car_started_for_night and car_running:
            car_started_for_night = True
            logger.info("Car started for night")
        if car_started_for_night and not car_running and not worklight_on:
            worklight_on = True
            logger.info("Car off, turning worklight on")
            GPIO.output(LIGHT_RELAY_PIN, 1)
        if car_started_for_night and car_running and worklight_on:
            worklight_on = False
            logger.info("Car back on, turning worklight off")
            GPIO.output(LIGHT_RELAY_PIN, 0)
        await asyncio.sleep(1)


async def init_main(args, dispatcher):
    server = AsyncIOOSCUDPServer((args.ip, args.port), dispatcher, asyncio.get_event_loop())
    transport, protocol = await server.create_serve_endpoint()

    await loop()

    transport.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default="192.168.86.30") #192.168.1.12")
    parser.add_argument("--port", type=int, default=8888, help="The port to listen on")
    args = parser.parse_args()

    dispatcher = Dispatcher()
    dispatcher.map("/light", handle_light)

    logger.info(f'Serving on {args.ip}:{args.port}')

    asyncio.run(init_main(args, dispatcher))
