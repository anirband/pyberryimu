#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
:mod:`accelerometer`
==================

.. module:: accelerometer
   :platform: Unix, Windows
   :synopsis: 

.. moduleauthor:: hbldh <henrik.blidh@nedomkull.com>

Created on 2015-05-19, 22:52

"""

from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals
from __future__ import absolute_import

import os
import json
import time

import numpy as np

from pyberryimu import version
from pyberryimu.exc import PyBerryIMUError
from pyberryimu.calibration.base import BerryIMUCalibration


class StandardCalibration(BerryIMUCalibration):
    """The Standard Calibration object for the PyBerryIMU."""

    def __init__(self, verbose=False):
        """Constructor for StandardCalibration"""
        super(StandardCalibration, self).__init__()

        self.pyberryimu_version = version
        self._verbose = verbose

        # BerryIMU settings for the client used for calibration.
        self.berryimu_settings = None

        # Accelerometer calibration parameters.
        self.acc_zero_g = None
        self.acc_sensitivity = None
        self.acc_scale_factor_matrix = None
        self.acc_bias_vector = None

        # Gyroscope calibration parameters.
        # TODO: Remove default values here after implementation of gyro calibration.
        self.gyro_zero = np.array([0, 0, 0], 'float')
        self.gyro_sensitivity = np.array([1, 1, 1], 'float')

    @classmethod
    def load(cls, doc_path=os.path.expanduser('~/.pyberryimu')):
        with open(doc_path, 'rt') as f:
            doc = json.load(f)

        out = cls()

        # Transfer BerryIMU settings.
        out.berryimu_settings = doc.get('pyberryimu_version', version)
        out.pyberryimu_version = doc.get('BerryIMU_settings', {})

        # Parse accelerometer calibration values.
        acc_doc = doc.get('accelerometer', {})
        out.acc_zero_g = np.array(acc_doc.get('zero', [0, 0, 0]), 'float')
        out.acc_sensitivity = np.array(acc_doc.get('sensitivity', [1, 1, 1]), 'float')
        out.acc_scale_factor_matrix = np.reshape(
            np.array(acc_doc.get('scale_factor', np.eye(3).flatten()), 'float'), (3, 3))
        out.acc_bias_vector = np.array(acc_doc.get('bias', [0, 0, 0]), 'float')

        # Parse gyroscope calibration values.
        gyro_doc = doc.get('gyroscope', {})
        out.gyro_zero = np.array(gyro_doc.get('zero', [0, 0, 0]), 'float')
        out.gyro_sensitivity = np.array(gyro_doc.get('sensitivity', [1, 1, 1]), 'float')

        return out

    def save(self, save_path=os.path.expanduser('~/.pyberryimu')):
        try:
            doc = {
                'BerryIMU_settings': self.berryimu_settings,
                'accelerometer': {
                    'zero': self.acc_zero_g.tolist(),
                    'sensitivity': self.acc_sensitivity.tolist(),
                    'scale_factor': self.acc_scale_factor_matrix.flatten().tolist(),
                    'bias': self.acc_bias_vector.tolist()
                },
                'gyro': {
                    'zero': self.gyro_zero.tolist(),
                    'sensitivity': self.gyro_sensitivity.tolist(),
                }
            }
        except Exception as e:
            raise PyBerryIMUError("Could not save ")
        with open(save_path, 'wt') as f:
            json.dump(doc, f, indent=4)

    def to_json(self):
        return {
            'pyberryimu_version': version,
            'BerryIMU_settings': self.berryimu_settings,
            'accelerometer': {
                'zero': self.acc_zero_g.tolist(),
                'sensitivity': self.acc_sensitivity.tolist(),
                'scale_factor': self.acc_scale_factor_matrix.flatten().tolist(),
                'bias': self.acc_bias_vector.tolist()
            },
            'gyro': {
                'zero': self.gyro_zero.tolist(),
                'sensitivity': self.gyro_sensitivity.tolist(),
            }
        }

    def calibrate_accelerometer(self, client):
        """Perform calibration of accelerometer.

        Computes the Zero G levels, Sensitivity, Scale factor Matrix and the
        bias vector of a MEMS accelerometer.

        The procedure exploits the fact that, in static conditions, the
        modulus of the accelerometer output vector matches that of the
        gravity acceleration. The calibration model incorporates the bias
        and scale factor for each axis and the cross-axis symmetrical
        factors. The parameters are computed through Gauss-Newton
        nonlinear optimization.

        The mathematical model used is  A = M(V - B)
        where M and B are scale factor matrix and bias vector respectively.

        M = [ Mxx Mxy Mxz; Myx Myy Myz; Mzx Mzy Mzz ]
        where  Mxy = Myx; Myz = Mzy; Mxz = Mzx;
        B = [ Bx; By; Bz ]

        The diagonal elements of M represent the scale factors along the
        three axes, whereas the other elements of M are called cross-axis
        factors. These terms allow describing both the axes’ misalignment
        and the crosstalk effect between different channels caused
        by the sensor electronics. In an ideal world, M = 1; B = 0

        To convert raw measurements to units of g use the following formula:
        Vx_g = (Vx - Zero_x)* Sensitivity_x
        Vy_g = (Vy - Zero_y)* Sensitivity_y
        Vz_g = (Vz - Zero_z)* Sensitivity_z

        To find the zero values of your own accelerometer, note the max and
        minimum of the ADC values for each axis and use the following formula:
        Zero_x = (Max_x - Min_x)/2; Zero_y = (Max_y - Min_y)/2; Zero_z = (Max_z - Min_z)/2
        To find the Sensitivity use the following formula:
        Sensitivity_x = 2 / (Max_x - Min_x);

        Reference:
        Iuri Frosio, Federico Pedersini, N. Alberto Borghese
        "Autocalibration of MEMS Accelerometers"
        IEEE TRANSACTIONS ON INSTRUMENTATION AND MEASUREMENT, VOL. 58, NO. 6, JUNE 2009

        This is a Python reimplementation of the Matlab routines found at
        `Matlab File Central <http://se.mathworks.com/matlabcentral/fileexchange/
        33252-mems-accelerometer-calibration-using-gauss-newton-method>`_.

        :param client: The BerryIMU communication client.
        :type client: :py:class:`pyberryimu.client.BerryIMUClient`

        """
        if self.acc_zero_g is not None:
            raise PyBerryIMUError('This object has already been calibrated!')

        self.berryimu_settings = client.get_settings()
        points = self._do_six_point_one_g_calibration(client)
        points += self._add_additional_points(client)
        # Apply the zero G and sensitivity knowledge and then run optimization.
        points = (np.array(points) - self.acc_zero_g) * self.acc_sensitivity
        self._perform_calibration_optimisation(points)

    def _do_six_point_one_g_calibration(self, client):
        points = []
        self.acc_zero_g = np.zeros((3, ), 'float')
        self.acc_sensitivity = np.zeros((3, ), 'float')

        # Method for polling until desired axis is oriented as requested.
        def _wait_for_compliance():
            keep_waiting = 10
            while keep_waiting > 0:
                a = client.read_accelerometer()
                norm_a = np.linalg.norm(a)
                norm_diff = np.abs(np.abs(a[index]) - norm_a) / norm_a

                if norm_diff < 0.05 and cmp(a[index], 0) == side:
                    keep_waiting -= 1
                else:
                    keep_waiting = 10
                time.sleep(0.1)

        axes_names = ['x', 'y', 'z']
        for index in xrange(3):
            this_axis_points = []
            for side in [-1, 1]:
                print('Position BerryIMU {0} axis {1}...'.format(
                    axes_names[index], 'downwards' if side < 0 else 'upwards'))
                _wait_for_compliance()
                raw_input('Correct orientation. Start calibration of BerryIMU {0} '
                          'axis {1} ({2}) by pressing Enter.'.format(axes_names[index],
                                                                     'downwards' if side < 0 else 'upwards',
                                                                     client.read_accelerometer()))
                acc_values = []
                t = time.time()
                while (time.time() - t) < 5:
                    acc_values.append(client.read_accelerometer())

                points.append(np.mean(acc_values, axis=0).tolist())
                this_axis_points.append(points[-1][index])

            v_max, v_min = max(this_axis_points), min(this_axis_points)
            self.acc_zero_g[index] = (v_max + v_min) / 2
            self.acc_sensitivity[index] = 2 / (v_max - v_min)

        return points

    def _add_additional_points(self, client):
        """Add more calibration points.

        Six calibration points have already been recorded in the six direction zero G/sensitivity
        part of the calibration. At least three more has to be added to be able to perform optimisation
        for scale factors and bias.

        :param client: The BerryIMU communication client.
        :type client: :py:class:`pyberryimu.client.BerryIMUClient`
        :return: List of points added.
        :rtype: list

        """
        points = []
        while True:
            ch = raw_input('At least {0} more points are required. '
                           'Add another calibration point? (y / n) '.format(max([3 - len(points), 0])))
            if ch == 'y':
                raw_input('Make sure BerryIMU is static and then start gathering data by pressing Enter.')
                acc_values = []
                t = time.time()
                while (time.time() - t) < 5:
                    acc_values.append(client.read_accelerometer())
                points.append(np.mean(acc_values, axis=0).tolist())
            elif ch == 'n':
                break
            else:
                pass
        return points

    def _perform_calibration_optimisation(self, points):
        """Perform the Gauss-Newton optimisation for parameters.

        :param points: The calibration points recorded.
        :type points: :py:class:`numpy.ndarray`

        """
        nbr_points = len(points)
        if nbr_points < 9:
            raise ValueError('Need at least 9 Measurements for the calibration procedure!')

        # Optimisation error function.
        error_function = lambda M, b, y: np.sum((M.dot((b - y)) ** 2)) - 1

        # Method for calculating the Jacobian.
        def _jacobian(M_mat, b_vec, point):
            # TODO: Clean up Jacobian calculation code.
            jac = np.zeros((9, ), 'float')

            jac[0] = 2 * (b_vec[0] - point[0]) * (
                M_mat[0, 0] * (b_vec[0] - point[0]) + M_mat[0, 1] * (b_vec[1] - point[1]) + M_mat[0, 2] * (
                b_vec[2] - point[2]))
            jac[1] = 2 * (b_vec[1] - point[1]) * (
                M_mat[0, 0] * (b_vec[0] - point[0]) + M_mat[0, 1] * (b_vec[1] - point[1]) + M_mat[0, 2] * (
                    b_vec[2] - point[2])) + 2 * (b_vec[0] - point[0]) * (
                M_mat[0, 1] * (b_vec[0] - point[0]) + M_mat[1, 1] * (b_vec[1] - point[1]) + M_mat[1, 2] * (
                b_vec[2] - point[2]))
            jac[2] = 2 * (b_vec[0] - point[0]) * (
                M_mat[0, 2] * (b_vec[0] - point[0]) + M_mat[1, 2] * (b_vec[1] - point[1]) + M_mat[2, 2] * (
                    b_vec[2] - point[2])) + 2 * (b_vec[2] - point[2]) * (
                M_mat[0, 0] * (b_vec[0] - point[0]) + M_mat[0, 1] * (b_vec[1] - point[1]) + M_mat[0, 2] * (
                b_vec[2] - point[2]))
            jac[3] = 2 * (b_vec[1] - point[1]) * (
                M_mat[0, 1] * (b_vec[0] - point[0]) + M_mat[1, 1] * (b_vec[1] - point[1]) + M_mat[1, 2] * (
                b_vec[2] - point[2]))
            jac[4] = 2 * (b_vec[1] - point[1]) * (
                M_mat[0, 2] * (b_vec[0] - point[0]) + M_mat[1, 2] * (b_vec[1] - point[1]) + M_mat[2, 2] * (
                    b_vec[2] - point[2])) + 2 * (b_vec[2] - point[2]) * (
                M_mat[0, 1] * (b_vec[0] - point[0]) + M_mat[1, 1] * (b_vec[1] - point[1]) + M_mat[1, 2] * (
                b_vec[2] - point[2]))
            jac[5] = 2 * (b_vec[2] - point[2]) * (
                M_mat[0, 2] * (b_vec[0] - point[0]) + M_mat[1, 2] * (b_vec[1] - point[1]) + M_mat[2, 2] * (
                b_vec[2] - point[2]))
            jac[6] = 2 * M_mat[0, 0] * (
                M_mat[0, 0] * (b_vec[0] - point[0]) + M_mat[0, 1] * (b_vec[1] - point[1]) + M_mat[0, 2] * (
                    b_vec[2] - point[2])) + 2 * M_mat[0, 1] * (
                M_mat[0, 1] * (b_vec[0] - point[0]) + M_mat[1, 1] * (b_vec[1] - point[1]) + M_mat[1, 2] * (
                    b_vec[2] - point[2])) + 2 * M_mat[0, 2] * (
                M_mat[0, 2] * (b_vec[0] - point[0]) + M_mat[1, 2] * (b_vec[1] - point[1]) + M_mat[2, 2] * (
                b_vec[2] - point[2]))
            jac[7] = 2 * M_mat[0, 1] * (
                M_mat[0, 0] * (b_vec[0] - point[0]) + M_mat[0, 1] * (b_vec[1] - point[1]) + M_mat[0, 2] * (
                    b_vec[2] - point[2])) + 2 * M_mat[1, 1] * (
                M_mat[0, 1] * (b_vec[0] - point[0]) + M_mat[1, 1] * (b_vec[1] - point[1]) + M_mat[1, 2] * (
                    b_vec[2] - point[2])) + 2 * M_mat[1, 2] * (
                M_mat[0, 2] * (b_vec[0] - point[0]) + M_mat[1, 2] * (b_vec[1] - point[1]) + M_mat[2, 2] * (
                b_vec[2] - point[2]))
            jac[8] = 2 * M_mat[0, 2] * (
                M_mat[0, 0] * (b_vec[0] - point[0]) + M_mat[0, 1] * (b_vec[1] - point[1]) + M_mat[0, 2] * (
                    b_vec[2] - point[2])) + 2 * M_mat[1, 2] * (
                M_mat[0, 1] * (b_vec[0] - point[0]) + M_mat[1, 1] * (b_vec[1] - point[1]) + M_mat[1, 2] * (
                    b_vec[2] - point[2])) + 2 * M_mat[2, 2] * (
                M_mat[0, 2] * (b_vec[0] - point[0]) + M_mat[1, 2] * (b_vec[1] - point[1]) + M_mat[2, 2] * (
                b_vec[2] - point[2]))

            return jac

        # Convenience method for moving between optimisation vector and correct lin.alg. formulation.
        def optvec_to_M_and_b(v):
            return np.array([[v[0], v[1], v[2]], [v[1], v[3], v[4]], [v[2], v[4], v[5]]]), v[6:].copy()

        gain = 1  # Damping Gain - Start with 1
        damping = 0.01    # Damping parameter - has to be less than 1.
        tolerance = 1e-9
        R_prior = 100000
        nbr_iterations = 200

        # Initial Guess values of M and b.
        x = np.array([5, 0.5, 0.5, 5, 0.5, 5, 0.5, 0.5, 0.5])
        last_x = x.copy()
        # Residuals vector
        R = np.zeros((nbr_points, ), 'float')
        # Jacobian matrix
        J = np.zeros((nbr_points, 9), 'float')

        for n in xrange(nbr_iterations):
            # Calculate the Jacobian at every iteration.
            M, b = optvec_to_M_and_b(x)
            for i in xrange(nbr_points):
                R[i] = error_function(M, b, points[i, :])
                J[i, :] = _jacobian(M, b, points[i, :])

            # Calculate Hessian, Gain matrix and apply it to solution vector.
            H = np.linalg.inv(J.T.dot(J))
            D = J.T.dot(R).T
            x -= gain * (D.dot(H)).T
            R_post = np.linalg.norm(R)
            if self._verbose:
                print("{0}: {1} ({2})".format(n, R_post, ", ".join(["{0:0.9g}".format(v) for v in x])))

            # This is to make sure that the error is decreasing with every iteration.
            if R_post <= R_prior:
                gain -= damping * gain
            else:
                gain *= damping

            # Iterations are stopped when the following convergence criteria is satisfied.
            if abs(max(2 * (x - last_x) / (x + last_x))) <= tolerance:
                self.acc_scale_factor_matrix, self.acc_bias_vector = optvec_to_M_and_b(x)
                break

            last_x = x.copy()
            R_prior = R_post

    def calibrate_gyroscope(self, client):
        raise NotImplementedError("This has not been implemented yet.")

    def transform_accelerometer_values(self, acc_values):
        raw_g_values = (acc_values - self.acc_zero_g) * self.acc_sensitivity
        converted_g_values = self.acc_scale_factor_matrix.dot(raw_g_values - self.acc_bias_vector)
        return tuple(converted_g_values.tolist())

    def transform_gyroscope_values(self, gyro_values):
        return tuple(((gyro_values - self.gyro_zero) * self.gyro_sensitivity).tolist())

    def transform_magnetometer_values(self, mag_values):
        # TODO: Study magnetometer calibration. Needed? Zero level is already taken care of.
        return mag_values


def main():
    # V = np.array([[-0.009345794, 0.00952381, 1],
    #               [-1, -0.00952381, 0.044247788],
    #               [1, 0.028571429, 0.008849558],
    #               [-0.009345794, 1, -0.115044248],
    #               [0.028037383, -1, 0.008849558],
    #               [-0.775700935, -0.638095238, 0.008849558],
    #               [-0.570093458, 0.80952381, -0.026548673],
    #               [0.644859813, 0.771428571, -0.061946903],
    #               [0.775700935, -0.619047619, -0.115044248],
    #               [0.981308411, 0.00952381, -0.256637168]])
    V = np.array([[-1575.43324607, 58.07787958, -72.69371728],
                  [1189.53102547, -11.92749837, -23.37687786],
                  [-212.62989556, -1369.82898172, -48.73498695],
                  [-183.42717178, 1408.61463096, -33.89745265],
                  [-162.57253886, 23.43005181, -1394.36722798],
                  [-216.76963011, 19.37118754, 1300.13822193],
                  [-809.20208605, 69.1029987, -1251.60104302],
                  [-1244.03955901, -866.0843061, -67.02594034],
                  [-1032.3692107, 811.19178082, 699.69602087],
                  [-538.82617188, -161.6171875, -1337.34895833]])
    sc = StandardCalibration(True)
    sc.acc_zero_g = np.array(
        [(1189.53102547 + (-1575.43324607)) / 2,
         (1408.61463096 + (-1369.82898172)) / 2,
         (1300.13822193 + (-1394.36722798)) / 2])
    sc.acc_sensitivity = np.array(
        [2 / (1189.53102547 - (-1575.43324607)),
         2 / (1408.61463096 - (-1369.82898172)),
         2 / (1300.13822193 - (-1394.36722798))])
    V = (V - sc.acc_zero_g) * sc.acc_sensitivity
    sc._perform_calibration_optimisation(V)


if __name__ == "__main__":
    main()
