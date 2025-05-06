import tkinter as tk
from tkinter import ttk
import asyncio
from bleak import BleakScanner, BleakClient
from threading import Thread
from BTLE import BTLEDeviceConnector
import struct
import tkinter as tk
from tkinter import ttk
import asyncio
from bleak import BleakClient
import json
import os



def run_async_task(coro):
    """
    Run the given coroutine to completion on a dedicated background thread,
    so that the Tkinter mainloop is never blocked and the asyncio loop actually runs.
    """
    def _runner():
        # each thread needs its own event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        # run the coroutine (and any of its children) to completion
        loop.run_until_complete(coro)
        # if you want to keep subscriptions alive indefinitely, you could:
        loop.run_forever()

    Thread(target=_runner, daemon=True).start()


def parse_heart_rate(data: bytearray) -> int:
    """
    Parse BLE Heart Rate Measurement characteristic data.
    """
    # Flags in first byte: bit0=0 means uint8, bit0=1 means uint16
    if data[0] & 0x01 == 0:
        return data[1]
    return int.from_bytes(data[1:3], byteorder='little')

CONFIG_FILE = 'config.json'

class FitnessApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Fitness Control Panel")

        # User-set parameters
        self.ftp = 200
        self.target_hr = 140
        self.power=0
        self.cadence=None
        # Live stats variables
        self.elapsed_time = tk.StringVar(value="00:00")
        self.avg_power = tk.StringVar(value="0 W")
        self.current_power = tk.StringVar(value="0 W")
        self.current_hr = tk.StringVar(value="0 bpm")

        # BLE connector
        self.btle = BTLEDeviceConnector()
        self.connected_power_trainer_name = tk.StringVar(value="Not connected")
        self.connected_hr_monitor_name = tk.StringVar(value="Not connected")

        self._clients = []
        # arrange to clean up on close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self._last_crank_revs = None         # type: int
        self._last_crank_event_time = None   # type: int 
        self.current_cadence=tk.StringVar(value="0 RPM")
        self.load_config()
        self.build_gui()

    def build_gui(self):
        # Power Trainer row
        tk.Label(self.root, text="Power Trainer:").grid(row=0, column=0, sticky="e")
        tk.Button(self.root, text="Go", command=self.run_script_1).grid(row=0, column=1)
        tk.Label(self.root, textvariable=self.connected_power_trainer_name).grid(row=0, column=2, sticky="w")

        # HR Monitor row
        tk.Label(self.root, text="HR Monitor:").grid(row=1, column=0, sticky="e")
        tk.Button(self.root, text="Go", command=self.run_script_2).grid(row=1, column=1)
        tk.Label(self.root, textvariable=self.connected_hr_monitor_name).grid(row=1, column=2, sticky="w")

        # Start Sequence
        tk.Button(self.root, text="Start Sequence", command=self.start_sequence, width=20).grid(row=2, column=0, columnspan=2, pady=10)

        # FTP Setting
        tk.Label(self.root, text="FTP:").grid(row=3, column=0, sticky="e")
        self.ftp_label = tk.Label(self.root, text=f"{self.ftp} W")
        self.ftp_label.grid(row=3, column=1)
        tk.Button(self.root, text="-", command=self.decrease_ftp, width=3).grid(row=3, column=2)
        tk.Button(self.root, text="+", command=self.increase_ftp, width=3).grid(row=3, column=3)

        # Target HR Setting
        tk.Label(self.root, text="Target HR:").grid(row=4, column=0, sticky="e")
        self.hr_label = tk.Label(self.root, text=f"{self.target_hr} bpm")
        self.hr_label.grid(row=4, column=1)
        tk.Button(self.root, text="-", command=self.decrease_hr, width=3).grid(row=4, column=2)
        tk.Button(self.root, text="+", command=self.increase_hr, width=3).grid(row=4, column=3)

        # Separator
        ttk.Separator(self.root, orient="horizontal").grid(row=5, columnspan=4, sticky="ew", pady=10)

        # Stats display (including cadence)
        stats = [
            ("Elapsed Time:", self.elapsed_time),
            ("Average Power:", self.avg_power),
            ("Current Power:", self.current_power),
            ("Current Heart Rate:", self.current_hr),
            ("Cadence:", self.current_cadence)
        ]
        for idx, (label, var) in enumerate(stats, start=6):
            tk.Label(self.root, text=label).grid(row=idx, column=0, sticky="e")
            tk.Label(self.root, textvariable=var).grid(row=idx, column=1, sticky="w")

    # FTP controls
    def increase_ftp(self):
        self.ftp += 5
        self.ftp_label.config(text=f"{self.ftp} W")

    def decrease_ftp(self):
        self.ftp -= 5
        self.ftp_label.config(text=f"{self.ftp} W")

    # HR target controls
    def increase_hr(self):
        self.target_hr += 1
        self.hr_label.config(text=f"{self.target_hr} bpm")

    def decrease_hr(self):
        self.target_hr -= 1
        self.hr_label.config(text=f"{self.target_hr} bpm")

    def start_sequence(self):
        print(f"Starting sequence with FTP={self.ftp}, Target HR={self.target_hr}")

    def save_config(self):
        config = {
            "ftp": self.ftp,
            "target_hr": self.target_hr,
            "power_trainer": self.connected_power_trainer_name.get(),
            "hr_monitor": self.connected_hr_monitor_name.get()
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f)
        print(f"Configuration saved to {CONFIG_FILE}")
        
    def load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
            # restore values
            self.ftp = config.get("ftp", self.ftp)
            self.target_hr = config.get("target_hr", self.target_hr)
            # update labels after build_gui sets them
            print(f"Loaded config: FTP={self.ftp}, Target HR={self.target_hr}")
        except Exception as e:
            print(f"Failed to load config: {e}")
            
    def on_closing(self):
        """Called when the user closes the window—disconnect all BLE clients first."""
        self.save_config()
        async def disconnect_all():
            for client in self._clients:
                try:
                    await client.disconnect()
                    print(f"Disconnected {client.address}")
                except Exception as e:
                    print(f"Error disconnecting {client.address}: {e}")

        # run the disconnect coroutine to completion before destroying GUI
        asyncio.run(disconnect_all())
        # now close the Tkinter window
        self.root.destroy()


    # Device selection and connection
    def run_script_1(self):
        async def task():
            devices = await self.btle.discover_devices_with_characteristic(
                BTLEDeviceConnector.CYCLING_POWER_CONTROL_UUID
            )
            self.root.after(0, lambda: DeviceSelectionWindow(
                self.root,
                devices,
                lambda d: self.connect_to_device(d, self.on_power_trainer_connected),
                title="Select Power Trainer"
            ))
        run_async_task(task())


    def run_script_2(self):
        """Select and connect to a heart rate monitor"""
        print("Scanning for HR monitors")
        async def task():
            devices = await self.btle.discover_devices_with_characteristic(
                self.btle.HEART_RATE_UUID
            )
            self.root.after(0, lambda: DeviceSelectionWindow(
                self.root,
                devices,
                lambda device: self.connect_to_device(device, self.on_hr_monitor_connected),
                title="Select Heart Rate Monitor"
            ))
        run_async_task(task())

    def connect_to_device(self, device, callback):
        """Schedule connect and callback in asyncio loop"""
        async def task():
            client = BleakClient(device.address)
            await client.connect()
            print(f"Connected to {device.name or device.address}")
            self._clients.append(client)
            await callback(client)
        run_async_task(task())

        
    async def on_power_trainer_connected(self, client):
        self.power_client = client
        # ensure you have a StringVar for cadence
        self.current_cadence = tk.StringVar(value="0 RPM")
        # subscribe
        await client.start_notify(
            self.btle.CYCLING_POWER_MEASUREMENT_UUID,
            self.power_handler
        )

    
    def power_handler(self, sender, data: bytearray):
        # parse power
        self.power = int.from_bytes(data[2:4], byteorder="little", signed=True)
        print(f"Current power:{self.power}")
        # parse flags
        flags = int.from_bytes(data[0:2], byteorder="little")
        has_crank = bool(flags & (1 << 5))
        cadence=None
        if has_crank:
            # parse crank data
            offset = 4
            revs = int.from_bytes(data[offset:offset+4], byteorder="little")
            evt = int.from_bytes(data[offset+4:offset+6], byteorder="little")
            # compute delta
            if self._last_crank_revs is not None and self._last_crank_event_time is not None:
                dr = revs - self._last_crank_revs
                dt = (evt - self._last_crank_event_time) & 0xFFFF
                sec = dt / 1024.0 if dt else 0
                if sec > 0 and dr >= 0:
                    cadence = (dr / sec) * 60.0
                # save for next
            self._last_crank_revs = revs
            self._last_crank_event_time = evt
            # save for next
            print(self.cadence)
            self.cadence=cadence
            self._last_crank_revs = revs
            self._last_crank_event_time = evt

        # update GUI
        self.root.after(0, lambda: self.current_power.set(f"{self.power} W"))
        if cadence is not None:
            self.root.after(0, lambda: self.current_cadence.set(f"{cadence:.0f} RPM"))
            self.cadence = cadence
            
    async def set_erg_power(self, watts: int):
        """
        Send the FTMS ‘Set Target Power’ (op‑code 0x06) to the trainer.
        """
        FTMS_CTRL = self.btle.CYCLING_POWER_CONTROL_UUID  # 0x2AD9
        # pack: <B = op‑code, H = uint16 watts
        payload = struct.pack("<BH", 0x06, watts)
        # write with response so we know it went through
        await self.power_client.write_gatt_char(FTMS_CTRL, payload, response=True)
        print(f"Asked trainer to hold {watts} W")


    async def on_hr_monitor_connected(self, client):
        print("HR monitor connected.")
        # display device name
        try:
            name = await client.read_gatt_char("00002a00-0000-1000-8000-00805f9b34fb")
            decoded = name.decode(errors="ignore")
            self.root.after(0, lambda: self.connected_hr_monitor_name.set(decoded))
        except Exception:
            self.root.after(0, lambda: self.connected_hr_monitor_name.set(client.address))

        # subscribe to HR notifications
        def hr_handler(sender, data):
            hr = parse_heart_rate(data)
            self.root.after(0, lambda: self.current_hr.set(f"{hr} bpm"))
        await client.start_notify(self.btle.HEART_RATE_UUID, hr_handler)





class DeviceSelectionWindow(tk.Toplevel):
    def __init__(self, parent, devices, callback, title="Select Device"):
        super().__init__(parent)
        self.title(title)
        self.callback = callback
        self.devices = devices

        self.listbox = tk.Listbox(self, width=50)
        self.listbox.pack(padx=10, pady=10)

        for device in devices:
            self.listbox.insert(tk.END, f"{device.name or 'Unknown'} - {device.address}")

        tk.Button(self, text="Connect", command=self.select_device).pack(pady=(0, 10))

    def select_device(self):
        index = self.listbox.curselection()
        if index:
            device = self.devices[index[0]]
            self.callback(device)
            self.after(500, self.destroy)  # Close window after 500ms
            print(f"Device selected: {device.name or 'Unknown'}")
        else:
            print("No device selected")

            
# Run the app
if __name__ == "__main__":
    root = tk.Tk()
    app = FitnessApp(root)
    root.mainloop()
