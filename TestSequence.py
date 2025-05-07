import asyncio
import time
import struct
import json

class TestSequence:
    def __init__(self, power_client, get_current_hr, get_current_power, get_current_cadence,
                 set_power, ftp:int, zone2_pct:float=0.6,
                 hr_tolerance:int=2, stabilize_secs:int=20,
                 output_file:str="test_results.json"):
        self.client = power_client
        self.get_current_hr = get_current_hr
        self.get_current_power = get_current_power
        self.get_current_cadence = get_current_cadence
        self.set_power = set_power
        self.ftp = ftp
        self.zone2_power = int(zone2_pct * ftp)
        self.hr_tol = hr_tolerance
        self.stabilize_secs = stabilize_secs
        self.outfile = output_file
        self.samples = []
        self._start_time = None

    def log_sample(self):
        now = time.time()
        sample = {
            "timestamp": round(now - self._start_time, 1),
            "hr": self.get_current_hr(),
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
            
        
    async def wait_hr_stable(self,time_duration=20):
        """Wait until HR is stable for the given time."""
        print(f"Waiting for HR to stabilize ±{self.hr_tol} bpm...")
        hr0 = self.get_current_hr()
        last_change = time.time()

        while True:
            await asyncio.sleep(1)
            self.log_sample()
            hr = self.get_current_hr()
            if abs(hr - hr0) > self.hr_tol:
                hr0 = hr
                last_change = time.time()
                print(f"  HR jumped to {hr} → resetting timer")
            elif time.time() - last_change >= time_duration:
                print(f"  HR stabilized at {hr} bpm")
                return hr

    async def run(self):
        self.samples = []
        self._start_time = time.time()
        await self.wait_cadence_high()
        await asyncio.sleep(1)
        # enable ERG mode first (Request Control + Indication setup)
        await self.enable_erg_control()
        await asyncio.sleep(1)
        # STEP 1: zone2
        print(f"STEP 1: setting {self.zone2_power} W")
        try:
            await self.set_power(int(self.zone2_power))
        except Exception as e:
            print("set_power failed:", e)
        hr1 = await self.wait_hr_stable(time_duration=30)

        # STEP 2: FTP
        print(f"STEP 2: setting {self.ftp*0.9} W")
        await self.set_power(int(self.ftp*0.9))
        hr2 = await self.wait_hr_stable(time_duration=30)

        elapsed = time.time() - self._start_time
        result = {
            "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._start_time)),
            "zone2_power": self.zone2_power,
            "hr_after_zone2": hr1,
            "ftp_power": self.ftp,
            "hr_after_ftp": hr2,
            "elapsed_s": round(elapsed, 1),
            "samples": self.samples
        }

        try:
            with open(self.outfile, "a") as f:
                f.write(json.dumps(result) + "\n")
        except Exception as e:
            print("Failed to save:", e)

        return result
    
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




