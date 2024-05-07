import sys
import time
import argparse
import pandas as pd
import numpy as np
import os
import json
import matplotlib.pyplot as plt
from PyQt5 import QtWidgets
from PyQt5.QtCore import pyqtSlot
from rtlsdr import RtlSdr
from scipy import signal as sig
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QGridLayout
from matplotlib.mlab import psd
import time

#*** THIS IS MORE COMPLICATED THAN IT SOUNDS
#Need to get the harmonics to work to spot frequencies that are interfering it seems like PSD does not do it justice. We need to scan it for: Frequency of wave (to get the harmonics), the strength of the signal, and the band of the signal *** THIS IS MORE COMPLICATED THAN IT SOUNDS

# Guidelines for choosing the number of samples to read from the RTL-SDR device

# 1. Choose a power of 2:
# This is important for efficient processing, especially when using Fast Fourier Transform (FFT) algorithms.
# Common choices include 131072 (2^17), 262144 (2^18), 524288 (2^19), and 1048576 (2^20).
#
# Example:
# num_samples = 131072

# 2. Consider the time resolution:
# The time duration of the captured signal is determined by the number of samples and the sample rate.
# For example, if you choose 131072 samples and have a sample rate of 2.4 MS/s (2,400,000 samples per second),
# the time duration of the captured data would be 131072 / 2,400,000 = 0.0547 seconds.
# This means that the data you're processing represents a signal captured over 54.7 milliseconds.
#
# Equation:
# time_duration = num_samples / sample_rate

# Example:
num_samples = 131072
sample_rate = 2.4e6  # 2.4 MS/s
time_duration = num_samples / sample_rate  # 0.0547 seconds, or 54.7 milliseconds


#this is good at finding FM radio stations... but AM radio stations are going to be a challange because bad antenna... but in theory if connection is good and no interference
#it should work well for AM signals... I wonder if I can create an app that will be able to tell what devices are interfering based on the frequency of the signal

def station_verification(radio, state, file_path):
    """
    Verifies the presence of radio stations in a database for a specific city by comparing
    given frequencies in Hertz against those registered in the FM band. This function now
    dynamically reads from a specified CSV file path to obtain the database of radio stations.

    Parameters:
    - radio (list of int): List of radio frequencies in Hertz to verify.
    - state (str): Name of the state where the radio stations are to be verified.
    - file_path (str): The file path to the CSV file containing the radio station database.

    Returns:
    - tuple of (np.ndarray, np.ndarray):
        - The first element is a NumPy array containing the frequencies (in MHz) of the radio stations
          that are not registered in the database.
        - The second element is a NumPy array containing the frequencies (in MHz) of the radio stations
          that are registered in the database.
    """
    
    df = pd.read_csv(file_path, delimiter=';', on_bad_lines='warn')
    df = df[(df['DEPARTAMENTO'] == state) & (df['BANDA'] == 'FM')]
    df['FRECUENCIA'] = df['FRECUENCIA'].str.replace(' MHz', '').astype(float)
    df = df[['FRECUENCIA']]
    df_array = df.values
    df_array = df_array.flatten()

    radio = np.array(radio)
    freq_array = radio / 1e6

    not_registered_stations = np.setdiff1d(freq_array, df_array)
    registered_stations = np.intersect1d(freq_array, df_array)

    print(f'Las emisoras que no están en la base de datos son: {not_registered_stations}\n'
          f'y las emisoras que si están son: {registered_stations}')

    return not_registered_stations, registered_stations

def detect_harmonics(radio_stations, harmonic_threshold=3, max_harmonic=10, shape_margin=1e3, bin_width=1e3):
    harmonic_candidates = []
    for station in radio_stations:
        freq = station['freq']
        psd = station['psd']
        harmonics = [freq * (i + 1) for i in range(1, max_harmonic + 1)]
        strong_harmonics = 0
        for harmonic in harmonics:
            for candidate in radio_stations:
                if abs(candidate['freq'] - harmonic) < shape_margin:
                    if check_psd_shape(candidate, radio_stations, bin_width):
                        strong_harmonics += 1
                    break
        if strong_harmonics >= harmonic_threshold:
            harmonic_candidates.append({'freq': freq, 'harmonics': strong_harmonics})

    return harmonic_candidates

def find_relative_frequency(radio):

    '''
    Esta funcion permite seleccionar las frecuencias en las cuales el psd es mayor
    y filtrar frecuencias muy cercanas con psd menores
    
    Arguments:
        radio -- Lista compuesta de  diccionarios el cual contiene informacion sobre cada frecuencia ['freq':, 'psd': , 'band': ,"array":]

    Returns:
        radio -- Lista compuesta de diccionarios posterior al filtrado ['freq':, 'psd': , 'band': ,"array":]
    '''
    try:
        current=radio[-1]
        last=radio[-2]
        diff_freq=abs(float(current["freq"])-float(last["freq"]))
        diff_psd=float(current["psd"])-float(last["psd"])
        print(current["psd"],last["psd"],diff_psd)
        if diff_freq == 1e5:
            min_psd=min(float(current["psd"]),float(last["psd"]))
            if min_psd == float(current["psd"]):
                radio.pop(-1)
                return radio
            else:
                radio.pop(-2)
                return radio
        else:
            return radio
    except IndexError as e:
        return radio

def tune_to_frequency(radio, true_frequency, lo_frequency):
    '''
    Sintoniza la frecuencia agregando un offset

    '''
    shifted_frequency = true_frequency + lo_frequency
    radio.center_freq = shifted_frequency
    print(f"Tuned to {true_frequency / 1e6} MHz (shifted to {shifted_frequency / 1e6} MHz)")


def find_highest_magnitudes(data, num_peaks=8, sample_rate=2.048e6, fft_size=1024):
    '''
    Sintoniza la frecuencia agregando un offset
    
    '''
    if len(data) < num_peaks:
        print("Not enough data points to find the desired number of peaks.")
        return [], []

    peak_indices = np.argpartition(data, -num_peaks)[-num_peaks:]
    peak_indices = peak_indices[np.argsort(-data[peak_indices])]
    bin_width = sample_rate / fft_size
    frequencies = peak_indices * bin_width
    return peak_indices, frequencies

def optimal_decimation(list_frequencies):
    pass

class ScannerApp(QtWidgets.QMainWindow):
    def __init__(self):
        super(ScannerApp, self).__init__()

        self.init_ui()
        self.show()

    def init_ui(self):
        self.setWindowTitle('RTL-SDR Scanner')
        self.resize(400, 300)

        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)

        grid = QtWidgets.QGridLayout(central_widget)

        labels = ['PPM', 'Gain', 'Threshold', 'LNB LO', 'Start', 'Stop', 'Step', 'City']
        self.inputs = {}

        default_values = {'ppm': '5', 'gain': '25', 'threshold': '0.4', 'lnb lo': '-125000000', 'start': '87000000', 'stop': '108500000', 'step': '100000', 'city': 'CALDAS'}

        for i, label_text in enumerate(labels):
            label = QtWidgets.QLabel(label_text)
            input = QtWidgets.QLineEdit()
            input.setText(default_values[label_text.lower()])
            grid.addWidget(label, i, 0)
            grid.addWidget(input, i, 1)

            self.inputs[label_text.lower()] = input

        self.scan_button = QtWidgets.QPushButton('Start Scan')
        self.scan_button.clicked.connect(self.start_scan)
        grid.addWidget(self.scan_button, len(labels), 0, 1, 2)

        self.result_list = QtWidgets.QListWidget()
        grid.addWidget(self.result_list, 0, 2, len(labels), 1)

    @pyqtSlot()
    def start_scan(self):
        args = self.get_args()
        self.scan(args)

    def get_args(self):
        return argparse.Namespace(
            ppm=int(self.inputs['ppm'].text()),
            gain=int(self.inputs['gain'].text()),
            threshold=float(self.inputs['threshold'].text()),
            lo=int(self.inputs['lnb lo'].text()),
            start=int(self.inputs['start'].text()),
            stop=int(self.inputs['stop'].text()),
            step=int(self.inputs['step'].text()),
            city=str(self.inputs['city'].text()),
        )

    def scan(self, args):
        sdr = RtlSdr()
        sdr.sample_rate = sample_rate = 2400000
        sdr.err_ppm = args.ppm
        sdr.gain = args.gain
        sdr.city = args.city
        lo_frequency = args.lo

        freq = args.start
        radio_stations = []
        radio = []
        last_detected_station = None
        min_distance = 200000  # Minimum distance between stations in Hz

        #Se tiene que variar el treshold de acuerdo a las potencia de la señal y la ubicacion en la cual estan
        radio_psd_threshold = 2.5e-07
        start=time.time()
        while freq <= args.stop:
            print(f"Scanning frequency: {freq / 1e6} MHz")
            tune_to_frequency(sdr, freq, lo_frequency)
            iq_samples = self.read_samples(sdr, freq)
            iq_samples = sig.decimate(iq_samples, 24)   

            f, psd = sig.welch(iq_samples, fs=sample_rate / 24, nperseg=1024)

            peak_indices, frequencies = find_highest_magnitudes(psd, num_peaks=1, sample_rate=sample_rate / 24, fft_size=1024)

            if peak_indices:
                    peak_index = peak_indices[0]
                    peak_frequency = frequencies[0]
                    peak_psd = psd[peak_index]
                    print(f"Peak frequency: {peak_frequency} Hz, PSD: {peak_psd}")

                    # Group nearby frequencies as one station
                    if peak_psd >= radio_psd_threshold:  # Check if the PSD value is above the radio station threshold

                        print(f"Strong signal found at {freq / 1e6} MHz, PSD: {peak_psd}")  # Print the strong signal as it is found
                        current_station={'freq': freq, 'psd': peak_psd, 'band': (freq / 1e6)}
                        #addition=find_relative_frequency(current_station,radio_stations[-1])
                       #print(addition)
                        radio_stations.append(current_station)
                        radio_stations=find_relative_frequency(radio_stations)
                        last_detected_station = radio_stations[-1]
                        print(last_detected_station)

                    if peak_psd >= args.threshold:
                        self.result_list.addItem('{:.3f} MHz - {:.2f}'.format(freq / 1e6, peak_psd * 100))


            freq += args.step

        sdr.close()

        print("\nDetected radio stations:")
        print(f"el tiempo que se demora es {time.time()-start}")
        for station in radio_stations:
            print(f"Band: {station['freq'] / 1e6} MHz - PSD: {station['psd']}")
            radio.append(station['freq'])

        station_verification(radio, args.city, "CODIGO EN PYTHON\\RTL-SDR-Scanner-Python\\SDR_SCANNER\\channels-534_radioemisoras.csv")
        return radio_stations




    @staticmethod
    def read_samples(sdr, freq):
        f_offset = 25000
        sample_rate = 2400000
        sdr.center_freq = freq - f_offset
        time.sleep(0.01) # originally, 0.06, but too slow
        iq_samples = sdr.read_samples(2**15) #originally 1221376, but too slow, the lower this is though the lower the PSD integrity is...btw must be powers of 2...
        iq_samples = iq_samples[0:600000]
        fc1 = np.exp(-1.0j * 2.0 * np.pi * f_offset / sample_rate * np.arange(len(iq_samples)))
        iq_samples = iq_samples * fc1
        return iq_samples


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    window = ScannerApp()
    sys.exit(app.exec_())
