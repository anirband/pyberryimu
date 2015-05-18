#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
:mod:`client`
==================

.. module:: client
   :platform: Unix, Windows
   :synopsis: 

.. moduleauthor:: hbldh <henrik.blidh@nedomkull.com>

Created on 2015-05-18, 11:51

"""

from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals
from __future__ import absolute_import

import math
import time

from smbus import SMBus

from pyberryimu.exc import PyBerryIMUError
from pyberryimu.sensors import LSM9DS0, BMP180


class BerryIMUClient(object):
    """"""

    def __init__(self, bus=1, acc_setup=1, gyro_setup=1, mag_setup=1, raw_output=False):
        """Constructor for BerryIMUClient"""

        self._bus = None

        # Init time settings.
        self._bus_no = bus
        self._acc_setup = acc_setup
        self._gyro_setup = gyro_setup
        self._mag_setup = mag_setup
        self._raw_output = raw_output

        self._bmp180_calibration = None

    @property
    def bus(self):
        if self._bus is not None:
            return self._bus
        else:
            self.open()
            return self.bus

    def open(self):
        try:
            self._bus = SMBus(self._bus_no)
        except IOError as e:
            # TODO: Handle these undocumented errors better.
            raise
        else:
            self._init_accelerometer()
            self._init_gyroscope()
            self._init_magnetometer()
            self._init_barometric_pressure_sensor()

    def close(self):
        if self._bus is not None:
            try:
                self._bus.close()
            except Exception as e:
                # TODO: Test what errors can occur and handle these better.
                print("Exception at closing of i2c bus: {0}".format(e))

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # Initialisation methods

    def _init_accelerometer(self):
        """Initialize the accelerometer according to the settings flag stored."""
        # TODO: Better init handling!
        if self._acc_setup == 1:
            # z,y,x axis enabled, continuous update, 100Hz data rate
            self._write_to_accelerometer(LSM9DS0.CTRL_REG1_XM, 0b01100111)
            # +/- 16G full scale
            self._write_to_accelerometer(LSM9DS0.CTRL_REG2_XM, 0b00100000)
        else:
            raise PyBerryIMUError("Invalid Accelerometer setup flag: {0}.".format(self._acc_setup))

    def _init_gyroscope(self):
        """Initialize the gyroscope according to the settings flag stored."""
        # TODO: Better init handling!
        if self._gyro_setup == 1:
            # Normal power mode, all axes enabled
            self._write_to_gyroscope(LSM9DS0.CTRL_REG1_G, 0b00001111)
            # Continuous update, 2000 dps full scale
            self._write_to_gyroscope(LSM9DS0.CTRL_REG4_G, 0b00110000)

            # Conversion constants for this setting [deg/s/LSB]
            # TODO: Wrap G_GAIN in automatic calculation of value.
            self.__G_GAIN = 0.070
            self.__RAD_TO_DEG = math.degrees(1)
            self.__PI = math.pi
            # TODO: Study Loop period dependency.
            # Loop period = 41ms.   This needs to match the time it takes each loop to run
            self.__LP = 0.041
        else:
            raise PyBerryIMUError("Invalid Gyroscope setup flag: {0}.".format(self._gyro_setup))

    def _init_magnetometer(self):
        """Initialize the magnetometer according to the settings flag stored."""
        # TODO: Better init handling!
        if self._mag_setup == 1:
            # Temp enable, M data rate = 50Hz
            self._write_to_magnetometer(LSM9DS0.CTRL_REG5_XM, 0b11110000)
            # +/-12gauss
            self._write_to_magnetometer(LSM9DS0.CTRL_REG6_XM, 0b01100000)
            # Continuous-conversion mode
            self._write_to_magnetometer(LSM9DS0.CTRL_REG7_XM, 0b00000000)
        else:
            raise PyBerryIMUError("Invalid Magnetometer setup flag: {0}.".format(self._mag_setup))

    def _init_barometric_pressure_sensor(self):
        """Initialize the Barometric Pressure Sensor."""
        # Read whole calibration EEPROM data
        self._bmp180_calibration = self.bus.read_i2c_block_data(BMP180.ADDRESS, BMP180.CALIB_DATA_REG, 22)
        self.__OVERSAMPLING = 3  # 0..3
        # TODO: Translate calibration bytes to data.

    def get_bmp180_chip_id_and_version(self):
        """Gets Chip ID and version for the BMP180 sensor.

        :return: Chip ID and Version number
        :rtype: tuple

        """
        return self.bus.read_i2c_block_data(BMP180.ADDRESS, BMP180.CHIP_ID_REG, 2)

    # Methods for writing to BerryIMU.

    def _write_to_accelerometer(self, register, value):
        self.bus.write_byte_data(LSM9DS0.ACC_ADDRESS, register, value)
        return -1

    def _write_to_gyroscope(self, register, value):
        self.bus.write_byte_data(LSM9DS0.GYR_ADDRESS, register, value)
        return -1

    def _write_to_magnetometer(self, register, value):
        self.bus.write_byte_data(LSM9DS0.MAG_ADDRESS, register, value)
        return -1

    # Methods for reading from BerryIMU.

    def _read(self, address, register_low_bit, register_high_bit):
        value = (self.bus.read_byte_data(address, register_low_bit) |
                 (self.bus.read_byte_data(address, register_high_bit) << 8))

        return value if value < 32768 else value - 65536

    # TODO: Add conversion to proper units in reading methods.
    # TODO: Add timestamp as output for all read methods?

    def read_accelerometer(self):
        """Method for reading values from the accelerometer.

        :return: The X, Y, and Z values of the accelerometer.
        :rtype: tuple

        """
        return (self._read(LSM9DS0.ACC_ADDRESS, LSM9DS0.OUT_X_L_A, LSM9DS0.OUT_X_H_A),
                self._read(LSM9DS0.ACC_ADDRESS, LSM9DS0.OUT_Y_L_A, LSM9DS0.OUT_Y_H_A),
                self._read(LSM9DS0.ACC_ADDRESS, LSM9DS0.OUT_Z_L_A, LSM9DS0.OUT_Z_H_A))

    def read_gyroscope(self):
        """Method for reading values from the gyroscope.

        :return: The X, Y, and Z values of the gyroscope.
        :rtype: tuple

        """
        # # Convert Gyro raw to degrees per second
        # rate_gyr_x = g_x * G_GAIN
        # rate_gyr_y = g_y * G_GAIN
        # rate_gyr_z = g_z * G_GAIN
        #
        #
        # #Calculate the angles from the gyro. LP = loop period
        # gyroXangle += rate_gyr_x * LP;
        # gyroYangle += rate_gyr_y * LP;
        # gyroZangle += rate_gyr_z * LP;

        return (self._read(LSM9DS0.GYR_ADDRESS, LSM9DS0.OUT_X_L_G, LSM9DS0.OUT_X_H_G),
                self._read(LSM9DS0.GYR_ADDRESS, LSM9DS0.OUT_Y_L_G, LSM9DS0.OUT_Y_H_G),
                self._read(LSM9DS0.GYR_ADDRESS, LSM9DS0.OUT_Z_L_G, LSM9DS0.OUT_Z_H_G))

    def read_magnetometer(self):
        """Method for reading values from the magnetometer.

        :return: The X, Y, and Z values of the magnetometer.
        :rtype: tuple

        """
        return (self._read(LSM9DS0.MAG_ADDRESS, LSM9DS0.OUT_X_L_M, LSM9DS0.OUT_X_H_M),
                self._read(LSM9DS0.MAG_ADDRESS, LSM9DS0.OUT_Y_L_M, LSM9DS0.OUT_Y_H_M),
                self._read(LSM9DS0.MAG_ADDRESS, LSM9DS0.OUT_Z_L_M, LSM9DS0.OUT_Z_H_M))

    def read_temperature(self):
        """Method for reading temperature values from the barometric pressure sensor.

        :return: The temperature value.
        :rtype: int

        """
        # TODO: Clean up calculation of temperature and pressure.
        self.bus.write_byte_data(BMP180.ADDRESS, BMP180.WRITE_REG, 0x2E)
        time.sleep(0.005)
        msb, lsb = self.bus.read_i2c_block_data(BMP180.ADDRESS, BMP180.READ_REG, 2)
        ut = (msb << 8) + lsb
    
        ac1, ac2, ac3, ac4, ac5, ac6, b1, b2, mb, mc, md = self._get_bmp180_calib_values()
        x1 = ((ut - ac6) * ac5) >> 15
        x2 = (mc << 11) // (x1 + md)
        b5 = x1 + x2
        t = (b5 + 8) >> 4
        return ut, t / 10.0

    def read_pressure(self):
        """Method for reading pressure value from the barometric pressure sensor.

        :return: The pressure value.
        :rtype: int

        """
        # TODO: Clean up calculation of temperature and pressure.

        ac1, ac2, ac3, ac4, ac5, ac6, b1, b2, mb, mc, md = self._get_bmp180_calib_values()

        self.bus.write_byte_data(BMP180.ADDRESS, BMP180.WRITE_REG, 0x2E)
        time.sleep(0.005)
        msb, lsb = self.bus.read_i2c_block_data(BMP180.ADDRESS, BMP180.READ_REG, 2)

        ut = (msb << 8) + lsb

        x1 = ((ut - ac6) * ac5) >> 15
        x2 = (mc << 11) // (x1 + md)
        b5 = x1 + x2
        t = (b5 + 8) >> 4

        self.bus.write_byte_data(BMP180.ADDRESS, BMP180.WRITE_REG, 0x34 + (self.__OVERSAMPLING << 6))
        time.sleep(0.04)
        msb, lsb, xsb = self.bus.read_i2c_block_data(BMP180.ADDRESS, BMP180.READ_REG, 3)
        up = ((msb << 16) + (lsb << 8) + xsb) >> (8 - self.__OVERSAMPLING)

        x1 = ((ut - ac6) * ac5) >> 15
        x2 = (mc << 11) // (x1 + md)
        b5 = x1 + x2

        b6 = b5 - 4000
        b62 = b6 * b6 >> 12
        x1 = (b2 * b62) >> 11
        x2 = ac2 * b6 >> 11
        x3 = x1 + x2
        b3 = (((ac1 * 4 + x3) << self.__OVERSAMPLING) + 2) >> 2

        x1 = ac3 * b6 >> 13
        x2 = (b1 * b62) >> 16
        x3 = ((x1 + x2) + 2) >> 2
        b4 = (ac4 * (x3 + 32768)) >> 15
        b7 = (up - b3) * (50000 >> self.__OVERSAMPLING)

        p = (b7 * 2) // b4
        # p = (b7 / b4) * 2

        x1 = (p >> 8) * (p >> 8)
        x1 = (x1 * 3038) >> 16
        x2 = (-7357 * p) >> 16
        p += (x1 + x2 + 3791) >> 4

        return p / 100.0

    def _get_bmp180_calib_values(self):
        vals = [msb + lsb for msb, lsb in zip(map(lambda x: x << 8, self._bmp180_calibration[::2]),
                                              self._bmp180_calibration[1::2])]
        for i in [0, 1, 2, 6, 7, 8, 9, 10]:
            if vals[i] > 2**15 - 1:
                vals[i] -= 2**16
        return vals
