import asyncio
import time
import json
from simple_pid import PID
import Plotter
from datetime import datetime
from pathlib import Path
import math

class Workout:
    def __init__(self, power_client, get_current_hr, get_current_power, get_current_cadence,
                 set_power, ftp:int,PID_params,get_target_hr,get_run,set_elapsed, set_avg_power,get_pid_params=None,
                 output_file:str=f"Workouts/test_results{datetime.now().strftime('%Y-%m-%d')}.json",log=None,max_step=10):
        self.client = power_client
        self.get_current_hr = get_current_hr
        self.get_current_power = get_current_power
        self.get_current_cadence = get_current_cadence
        self.get_pid_params=get_pid_params
        self.set_power = set_power
        self.ftp = ftp
        self.max_step=max_step
        self.outfile = output_file
        self.samples = []
        self.set_elapsed = set_elapsed
        self.set_avg_power = set_avg_power
        self._power_accumulator = 0.0
        self._power_count = 0
        self._start_time = None
        self.log = log or (lambda msg: None)
        self.get_target_hr=get_target_hr
        self.get_run=get_run
        self.start_up_time=60
        self._smoothed_hr = None
        self._alpha = 0.6  # Smoothing factor (tweak between 0.1 and 0.5)

        


        if get_pid_params is not None:
            kp, Ki, Kd = get_pid_params()
        else:
            kp, Ki, Kd = PID_params['Kp'], PID_params['Ki'], PID_params['Kd']

        self.kp = kp
        self.Ki = Ki
        self.Kd = Kd
        self.pid = PID(self.kp, self.Ki, self.Kd, setpoint=self.get_target_hr())
        #self.pid.integral_limits = (-2, 2)  # adjust based on your output range
        print(f"Kp: {self.pid.Kp:.4f}, Ki: {self.pid.Ki:.4f}, Kd: {self.pid.Kd:.4f}")
        self.pid.output_limits = (0.3*self.ftp, 1.3*self.ftp)


    def log_sample(self):
        now = time.time()
        sample = {
            "timestamp": round(now - self._start_time, 1),
            "hr": self.get_current_hr(),
            "target_hr":self.get_target_hr(),
            "power": self.get_current_power(),
            "cadence": self.get_current_cadence()
            
        }
        self.samples.append(sample)
    async def wait_cadence_high(self):
        print(f"Wait for the cadence to increase")
        while True:
            await asyncio.sleep(1)
            self.log_sample()
            cadence=self.get_current_cadence()
            if cadence>60:
                print(f"Cadence is {cadence} RPM. Starting Test")
                return True
            

    async def run(self):
        print("Entered run")
        erg_enabled=True
        self.samples = []
        avg=0
        self._start_time = time.time()
        self.log("Start to pedal with a cadence of 60 RPM or higher!")
        await asyncio.sleep(3)
        await self.wait_cadence_high()
        self.log(f"Starting the control loop")
        await asyncio.sleep(1)
        # enable ERG mode first (Request Control + Indication setup)
        await self.enable_erg_control()
        self.log(f"ERG activated")
        await asyncio.sleep(1)
        self._start_time = time.time()
                # Setup for target HR ramping
        true_target_hr = self.get_target_hr()
        start_hr = self.get_current_hr()
        ramp_duration = 150  # seconds to ramp from start_hr to target_hr
        ramp_start_time = time.time()

        while self.get_run():
            # compute elapsed
            if self.get_pid_params is not None:
                [kp,Ki,Kd]=self.get_pid_params()
                self.kp=kp
                self.Ki=Ki
                self.Kd=Kd
                self.pid.tunings=(self.kp,self.Ki,self.Kd)
            elapsed = time.time() - self._start_time
            if elapsed < self.start_up_time:
                upper_limit = self.ftp * (0.4 + 0.7 * (elapsed / self.start_up_time))  # goes from 0.4 to 1.3*FTP
            else:
                upper_limit = self.ftp * 1.1
            self.pid.output_limits = (0.3 * self.ftp, upper_limit)
            
            # Raw HR
            raw_hr = self.get_current_hr()

            # Apply exponential moving average smoothing
            if self._smoothed_hr is None:
                self._smoothed_hr = raw_hr  # Init on first run
            else:
                self._smoothed_hr = self._alpha * raw_hr + (1 - self._alpha) * self._smoothed_hr
            print(self._smoothed_hr)

            self.set_elapsed(elapsed)
            now = time.time()
            elapsed_ramp = time.time() - ramp_start_time

            def easing_expo_out(t, T, k=3):
                """Eases quickly at the start and slows near the end."""
                return 1 - math.exp(-k * t / T)

            if elapsed_ramp < ramp_duration:
                factor = easing_expo_out(elapsed_ramp, ramp_duration)
                target_hr = start_hr + (true_target_hr - start_hr) * factor
            else:
                target_hr = true_target_hr

            current_hr = self._smoothed_hr

            error = abs(target_hr - current_hr)
            if error < 1:
                current_hr = target_hr


            # update running average
            pw = self.get_current_power()
            


            self._power_accumulator += pw
            self._power_count   += 1
            avg = self._power_accumulator / self._power_count
            self.set_avg_power(avg)

            # PID step
            # PID step
            self.pid.setpoint = target_hr
            power = self.pid(current_hr)

            # Output smoothing
            self._last_power = self._last_power if hasattr(self, "_last_power") else power
            smoothed_power = 0.4 * power + 0.6 * self._last_power
            self._last_power = smoothed_power

            #if pw-power>self.max_step:
            #    power=pw-self.max_step
            #elif pw-power<self.max_step:
            #    power=pw+self.max_step
            
                
            cadence=self.get_current_cadence()
            if cadence < 60 and erg_enabled:
                erg_enabled = False
                await self.set_power(0)
                self.log("Cadence too low. ERG disabled.")
            elif cadence >= 60 and not erg_enabled:
                erg_enabled = True
                # maybe re‐arm to previous target power on next cycle
                self.log("Cadence recovered. ERG re‐enabled.")
            else:
                await self.set_power(int(smoothed_power))

                self.log(f"Setting power to {power:.0f}W")

            self.log_sample()
            await asyncio.sleep(1)
        await self.set_power(int(100))
        elapsed = time.time() - self._start_time
        result = {
            "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._start_time)),
            "ftp_power": self.ftp,
            "Averadge":avg,
            "elapsed_s": round(elapsed, 1),
            "samples": self.samples
        }
        Plotter.plot_power_and_hr(result)

        
        
        try:
            # Ensure the output folder exists
            Path(self.outfile).parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.outfile, "w") as f:
                f.write(json.dumps(result) + "\n")
        except Exception as e:
            print("Failed to save:", e)
            

    
    async def enable_erg_control(self):
        FTMS_CTRL = "00002ad9-0000-1000-8000-00805f9b34fb"

        
        # 1) subscribe to indications
        try:
            await self.client.start_notify(FTMS_CTRL, self._ftms_response_handler)
        except Exception as e:
            print("start_notify failed:", e)
        await asyncio.sleep(1)

        # 2) request control
        try:
            await self.client.write_gatt_char(FTMS_CTRL, b'\x00', response=True)
        except Exception as e:
            print("request-control (0x00) failed:", e)
        await asyncio.sleep(1)
        print("2")
        # 3) start/resume
        try:
            await self.client.write_gatt_char(FTMS_CTRL, b'\x07', response=True)
        except Exception as e:
            print("start/resume (0x07) failed:", e)
        await asyncio.sleep(1)

    def _ftms_response_handler(self, sender, data):
        print(f"[FTMS RESP] {data.hex()}")