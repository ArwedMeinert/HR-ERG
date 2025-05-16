import asyncio
import time
import json
from simple_pid import PID
import Plotter
from datetime import datetime
from pathlib import Path

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

        if get_pid_params is not None:
            kp, Ti, Td = get_pid_params()
        else:
            kp, Ti, Td = PID_params['Kp'], PID_params['Ti'], PID_params['Td']

        self.kp = kp
        self.Ki = kp / Ti
        self.Kd = kp * Td
        self.pid = PID(self.kp, self.Ki, self.Kd, setpoint=self.get_target_hr())

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
        
        while self.get_run():
            # compute elapsed
            if self.get_pid_params is not None:
                [kp,Ti,Td]=self.get_pid_params()
                self.kp=kp
                self.Ki=self.kp/Ti
                self.Kd=self.kp*Td
                self.pid.tunings=(self.kp,self.Ki,self.Kd)
            elapsed = time.time() - self._start_time
            self.set_elapsed(elapsed)
            target_hr=self.get_target_hr()
            current_hr=self.get_current_hr()
            # update running average
            pw = self.get_current_power()
            self._power_accumulator += pw
            self._power_count   += 1
            avg = self._power_accumulator / self._power_count
            self.set_avg_power(avg)

            # PID step
            self.pid.setpoint = target_hr
            power = self.pid(current_hr)
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
                await self.set_power(int(power))
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