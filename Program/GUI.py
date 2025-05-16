import tkinter as tk
from tkinter import ttk
import asyncio
from threading import Thread
from BTLE import BTLEDeviceConnector
import struct
import tkinter as tk
from tkinter import ttk
import asyncio
from bleak import BleakClient
import json
import os
import TestSequence
import WorkoutSequence
from datetime import datetime
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

CONFIG_DIR = "configs"
LAST_USER_FILE = os.path.join(CONFIG_DIR, "last_user.json")

class FitnessApp:
    def __init__(self, root):
        self.COLOR_ACTION="firebrick1"
        self.COLOR_DISABLED = "lightgrey"
        self.COLOR_START="SteelBlue1"
        self.COLOR_OK="lawn green"
        self.COLOR_IN_PROCESS="yellow2"

        
        self.root = root
        self.root.title("Fitness Control Panel")

        # User-set parameters
        self.ftp = 200
        self.target_hr = 140
        self.power=0
        self.cadence=0.0
        self.power_client=None
        self.hr_client=None
        # Live stats variables
        self.elapsed_time = tk.StringVar(value="00:00")
        self.avg_power = tk.StringVar(value="0 W")
        self.current_power = tk.StringVar(value="0 W")
        self.current_hr = tk.StringVar(value="0 bpm")

        # BLE connector
        self.btle = BTLEDeviceConnector()
        self.connected_power_trainer_name = tk.StringVar(value="Not connected")
        self.connected_hr_monitor_name = tk.StringVar(value="Not connected")
        
        self.connected_power_trainer_address=""
        self.connected_hr_monitor_address=""

        self.kp_mult = 1#35
        self.ki_mult = 1#10
        self.kd_mult = 1#1
        
        
        self._clients = []
        # arrange to clean up on close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self._last_crank_revs = None         # type: int
        self._last_crank_event_time = None   # type: int 
        self.current_cadence=tk.StringVar(value="0 RPM")
        self.mult=tk.DoubleVar(value=0)
        self.training_active = False  # Add this in __init__
        self.pid_params_import = {"Kp": -1, "Ti": -1, "Td": -1}
        self.build_gui()
        self.load_last_user()
        self.pid_available=not(self.pid_params_import.get("Kp", -1) < 0 or self.pid_params_import.get("Ti", -1) < 0 or self.pid_params_import.get("Td", -1) < 0)
        self.hr_connected=False
        self.power_connected=False
        
        mult_val = self.mult.get()
        self.pid_params={
                "Kp": self.pid_params_import["Kp"]*self.kp_mult*mult_val,
                "Ti": self.pid_params_import["Ti"]*self.ki_mult*mult_val,
                "Td": self.pid_params_import["Td"]*self.kd_mult*mult_val
            }
        self.update_pid_label()
        
        if not self.pid_available:
            self.ftp_min_button.config(bg=self.COLOR_START)
            self.ftp_max_button.config(bg=self.COLOR_START)
            self.hr_min_button.config(bg=self.COLOR_DISABLED)
            self.hr_max_button.config(bg=self.COLOR_DISABLED)
        else:
            self.ftp_min_button.config(bg=self.COLOR_DISABLED)
            self.ftp_max_button.config(bg=self.COLOR_DISABLED)
            self.hr_min_button.config(bg=self.COLOR_START)
            self.hr_max_button.config(bg=self.COLOR_START)
        #self.update_sequence_button_color()
        
    def build_gui(self):
        # Power Trainer row
        tk.Label(self.root, text="Power Trainer:").grid(row=0, column=0, sticky="e")
        self.power_button=tk.Button(self.root,text="Search",command=self.run_script_1,bg=self.COLOR_ACTION)
        self.power_button.grid(row=0, column=1)
        tk.Label(self.root, textvariable=self.connected_power_trainer_name).grid(row=0, column=2, sticky="w")

        
        # User profile input and button
        tk.Label(self.root, text="User:").grid(row=0, column=2, sticky="e")
        self.user_entry = tk.Entry(self.root)
        self.user_entry.grid(row=0, column=3, sticky="w")

        self.load_user_button = tk.Button(self.root, text="Load User", command=self.load_user_config, bg=self.COLOR_START)
        self.load_user_button.grid(row=0, column=4, padx=(5, 0))
        
        
        # HR Monitor row
        tk.Label(self.root, text="HR Monitor:").grid(row=1, column=0, sticky="e")
        self.hr_button=tk.Button(self.root,text="Search",command=self.run_script_2,bg=self.COLOR_ACTION)
        self.hr_button.grid(row=1, column=1)
        tk.Label(self.root, textvariable=self.connected_hr_monitor_name).grid(row=1, column=2, sticky="w")

        # Start Sequence
        self.start_sequence_button=tk.Button(self.root,text="Start Sequence",command=self.start_sequence,width=20)
        self.start_sequence_button.config(bg=self.COLOR_DISABLED)
        self.start_sequence_button.grid(row=2, column=0, columnspan=2, pady=10)
        
        

        # FTP Setting
        tk.Label(self.root, text="FTP:").grid(row=3, column=0, sticky="e")
        self.ftp_label = tk.Label(self.root, text=f"{self.ftp} W")
        self.ftp_label.grid(row=3, column=1)
        self.ftp_min_button = tk.Button(self.root, text="-", command=self.decrease_ftp, width=3)
        self.ftp_min_button.grid(row=3, column=2)

        self.ftp_max_button = tk.Button(self.root, text="+", command=self.increase_ftp, width=3)
        self.ftp_max_button.grid(row=3, column=3)
            
        # Target HR Setting
        tk.Label(self.root, text="Target HR:").grid(row=4, column=0, sticky="e")
        self.hr_label = tk.Label(self.root, text=f"{self.target_hr} bpm")
        self.hr_label.grid(row=4, column=1)
        self.hr_min_button = tk.Button(self.root, text="-", command=self.decrease_hr, width=3, bg=self.COLOR_START)
        self.hr_min_button.grid(row=4, column=2)

        self.hr_max_button = tk.Button(self.root, text="+", command=self.increase_hr, width=3, bg=self.COLOR_START)
        self.hr_max_button.grid(row=4, column=3)

        
            
            
        # PID Display (row 5 before stats start at 6)
        self.pid_label = tk.Label(self.root, text="PID: Kp=-, Ti=-, Td=-", font=("Arial", 10))
        self.pid_label.grid(row=5, column=2, columnspan=4, sticky="w", padx=10)


        # Separator
        ttk.Separator(self.root, orient="horizontal").grid(row=5, columnspan=2, sticky="ew", pady=10)

        
        # Start Training Button
        self.start_training_button = tk.Button(
            self.root, text="Start Training", bg="lightgreen", width=20,
            command=self.toggle_training
        )
        self.start_training_button.config(bg=self.COLOR_DISABLED)
        self.start_training_button.grid(row=6, column=0, columnspan=2, pady=5, sticky="e")

        # PID Aggressiveness Slider (row 6, column 2)
        

        

        self.aggressiveness_slider = ttk.Scale(
            self.root,
            from_=0.5,
            to=2,
            orient="vertical",
            variable=self.mult,
            command=self.update_aggressiveness
        )
        self.aggressiveness_slider.grid(row=7, column=2, rowspan=5, sticky="ns", padx=(20, 0), pady=(0, 10))

        self.aggressiveness_label = tk.Label(self.root, text="Aggressiveness: 1.00x")
        self.aggressiveness_label.grid(row=6, column=2, padx=(20, 0), sticky="s")

        # Stats display (including cadence)
        stats = [
            ("Elapsed Time:", self.elapsed_time),
            ("Average Power:", self.avg_power),
            ("Current Power:", self.current_power),
            ("Current Heart Rate:", self.current_hr),
            ("Cadence:", self.current_cadence)
        ]
        for idx, (label, var) in enumerate(stats, start=7):
            tk.Label(self.root, text=label).grid(row=idx, column=0, sticky="e")
            tk.Label(self.root, textvariable=var).grid(row=idx, column=1, sticky="w")
        
                # Separator before text output area
        ttk.Separator(self.root, orient="horizontal").grid(row=12, columnspan=4, sticky="ew", pady=10)

        # Log/output screen
        tk.Label(self.root, text="Console Output:").grid(row=13, column=0, sticky="nw")
        self.log_box = tk.Text(self.root, height=10, width=50, wrap="word", state="disabled", bg="#f0f0f0")
        self.log_box.grid(row=12, column=1, columnspan=3, sticky="w")

    
    def update_aggressiveness(self,val):
            val = float(val)
            self.mult.set(val)
            self.pid_params={
                "Kp": self.pid_params_import["Kp"]*self.kp_mult*val,
                "Ti": self.pid_params_import["Ti"]*self.ki_mult*val,
                "Td": self.pid_params_import["Td"]*self.kd_mult*val
            }
            self.update_pid_label()
            self.aggressiveness_label.config(text=f"Aggressiveness: {val:.2f}x")
            
    def log_message(self, message):
        self.log_box.config(state="normal")
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")  # Auto-scroll to the bottom
        self.log_box.config(state="disabled")


    def toggle_training(self):
        if not self.power_connected:
            print("Trainer not connected")
            self.log_message("Please connect a power trainer before Starting the workout!")
            return
        if not self.hr_connected:
            print("HR not connected")
            self.log_message("Please connect a Heart Rate Monitor before starting the workout!")
            return
        if not self.pid_available:
            print("No PID values saved")
            self.log_message("No PID Values Saved. Please run the Test Sequence first")
            return
        self.training_active = not self.training_active
        if self.training_active:
            
            self.start_training_button.config(text="Training Running", bg=self.COLOR_ACTION)
            self.log_message("Training started")
            print(f"Kp: {self.pid_params['Kp']}, Ki: {self.pid_params['Ti']}, Kd: {self.pid_params['Td']}")

            # make sure we have a client
            if not hasattr(self, "power_client"):
                self.log_message("Trainer not connected")
                self.toggle_training()  # stop
                return

            # helper getters
            get_pid= lambda: [self.pid_params["Kp"],self.pid_params["Ti"],self.pid_params["Td"]]
            get_hr = lambda: int(self.current_hr.get().split()[0] or 0)
            get_pow = lambda: int(self.current_power.get().split()[0] or 0)
            get_cad = lambda: int(self.current_cadence.get().split()[0] or 0)
            get_target_hr = lambda: self.target_hr
            get_run = lambda: self.training_active
            def set_elapsed(elapsed_s):
                # format as mm:ss or however you like
                m, s = divmod(int(elapsed_s), 60)
                self.elapsed_time.set(f"{m:02d}:{s:02d}")

            def set_avg_power(p):
                self.avg_power.set(f"{int(p)} W")
        

            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            seq = WorkoutSequence.Workout(
                power_client=self.power_client,
                get_current_hr=get_hr,
                get_current_power=get_pow,
                get_current_cadence=get_cad,
                set_power=self.set_erg_power,
                get_pid_params=get_pid,
                ftp=self.ftp,
                PID_params=self.pid_params,
                get_target_hr=get_target_hr,
                get_run=get_run,
                set_elapsed=set_elapsed,
                set_avg_power=set_avg_power,
                output_file=os.path.join("Workouts", f"Workouts_{timestamp}.json"),
                log=self.log_message
            )

            # schedule it and handle completion
            run_async_task(seq.run())


        else:
            self.start_training_button.config(text="Start Training", bg=self.COLOR_START)
            self.log_message("Training stopped")

    def update_sequence_button_color(self):
        # if we never loaded a valid PID (e.g. defaults are <0) → green
        p = self.pid_params
        no_pid = p.get("Kp", -1) < 0 or p.get("Ti", -1) < 0 or p.get("Td", -1) < 0
        color = self.COLOR_START if no_pid else self.COLOR_DISABLED
        self.start_sequence_button.config(bg=color)
        self.start_training_button.config(bg=self.COLOR_DISABLED)


    # FTP controls
    def increase_ftp(self):
        self.ftp += 5
        self.ftp_label.config(text=f"{self.ftp} W")

    def decrease_ftp(self):
        self.ftp -= 5
        self.ftp_label.config(text=f"{self.ftp} W")

    def update_pid_label(self):
        p = self.pid_params
        self.pid_label.config(text=f"PID: Kp={p['Kp']:.4f}, Ki={p['Ti']/p['Kp']:.1f}, Kd={p['Kp']*p['Td']:.1f}")
    
    # HR target controls
    def increase_hr(self):
        self.target_hr += 1
        self.hr_label.config(text=f"{self.target_hr} bpm")

    def decrease_hr(self):
        self.target_hr -= 1
        self.hr_label.config(text=f"{self.target_hr} bpm")

    def start_sequence(self):
        if not self.power_connected:
            print("Trainer not connected")
            self.log_message("Please connect a power trainer before Starting the test!")
            return
        if not self.hr_connected:
            print("HR not connected")
            self.log_message("Please connect a Heart Rate Monitor before starting the test!")
            return

        # extract current values safely
        def get_hr():
            try:
                return int(self.current_hr.get().split()[0])
            except:
                return 0

        def get_power():
            try:
                return int(self.current_power.get().split()[0])
            except:
                return 0

        def get_cadence():
            try:
                return int(self.current_cadence.get().split()[0])
            except:
                return 0


        # start sequence
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        seq = TestSequence.TestSequence(
            power_client=self.power_client,
            get_current_hr=get_hr,
            get_current_power=get_power,
            get_current_cadence=get_cadence,
            set_power=self.set_erg_power,
            ftp=self.ftp,
            output_file = os.path.join("StepResponseTests", f"Test_Sequence_{timestamp}.json"),
            log=self.log_message
        )

        async def do_sequence_and_update():
            # Run the test and wait for its results
            result, pid_params = await seq.run()

            # 1) Store the new PID parameters
            self.pid_params_import = pid_params
            
            # 2) Update the on-screen PID display on the main thread
            self.root.after(0, self.update_pid_label)

            # 3) Mark PID available & enable buttons
            self.pid_available = True
            self.root.after(0, lambda: self.start_sequence_button.config(bg=self.COLOR_DISABLED))
            self.root.after(0, lambda: self.start_training_button.config(bg=self.COLOR_START))
            self.root.after(0, lambda:self.ftp_min_button.config(bg=self.COLOR_DISABLED))
            self.root.after(0, lambda:self.ftp_max_button.config(bg=self.COLOR_DISABLED))
            self.root.after(0, lambda:self.hr_min_button.config(bg=self.COLOR_START))
            self.root.after(0, lambda:self.hr_max_button.config(bg=self.COLOR_START))

            # 4) Save them immediately in the user config
            self.save_config()
            self.update_pid_label()

        # Schedule that combined task
        run_async_task(do_sequence_and_update())
        


    def save_config(self):
        username = self.user_entry.get().strip().lower()
        if not username:
            print("No username set. Cannot save config.")
            return

        config_path = os.path.join(CONFIG_DIR, f"{username}.json")
        
        try:
            config = {
                "ftp": self.ftp,
                "target_hr": self.target_hr,
                "power_trainer": self.connected_power_trainer_name.get() if self.connected_power_trainer_name else "",
                "power_trainer_address": self.connected_power_trainer_address if hasattr(self, "connected_power_trainer_address") else "",
                "hr_monitor": self.connected_hr_monitor_name.get() if self.connected_hr_monitor_name else "",
                "hr_monitor_address": self.connected_hr_monitor_address if hasattr(self, "connected_hr_monitor_address") else "",
                "pid_params": self.pid_params_import,
                "aggressiveness": self.mult.get()
            }

            os.makedirs(CONFIG_DIR, exist_ok=True)  # Ensure directory exists

            with open(config_path, 'w') as f:
                json.dump(config, f, indent=4)

            # Also update last user
            with open(LAST_USER_FILE, "w") as f:
                json.dump({"last_user": username}, f)

            print(f"Configuration saved for user '{username}' to {config_path}")
        except Exception as e:
            print(f"Failed to save config: {e}")


    def load_last_user(self):
        try:
            # Ensure the directory exists
            os.makedirs(CONFIG_DIR, exist_ok=True)

            # Create file with default if it doesn't exist
            if not os.path.exists(LAST_USER_FILE):
                with open(LAST_USER_FILE, "w") as f:
                    json.dump({"last_user": "default"}, f)
                    self.user_entry.delete(0, tk.END)
                    self.user_entry.insert(0, "default")
                    self.save_last_user("default")
                    

            # Read file
            with open(LAST_USER_FILE, "r") as f:
                data = json.load(f)

            username = data.get("last_user", "")
            
            self.user_entry.delete(0, tk.END)
            self.user_entry.insert(0, username)
            self.load_user_config()  # Load based on inserted user
        except Exception as e:
            print(f"Could not load last user: {e}")

    def save_last_user(self, username):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(LAST_USER_FILE, "w") as f:
                json.dump({"last_user": username}, f)
        except Exception as e:
            print(f"Could not save last user: {e}")



    def disconnect_all(self):
        async def _dc():
            for c in self._clients:
                try: await c.disconnect()
                except: pass
        asyncio.run(_dc())
        self._clients.clear()
        self.hr_client = None
        self.power_client = None
        self.hr_connected = self.power_connected = False
        # reset buttons…
        self.power_button.config(bg=self.COLOR_ACTION)
        self.hr_button   .config(bg=self.COLOR_ACTION)


    def load_user_config(self):
        username = self.user_entry.get().strip().lower()
        if not username:
            print("No username entered.")
            return
        #self.disconnect_all()
        config_path = os.path.join(CONFIG_DIR, f"{username}.json")

        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                config = json.load(f)
            print(f"Loaded config for user '{username}'")

        else:
            print(f"No config for '{username}', creating new one with defaults.")
            config = {
                "ftp": 200,
                "target_hr": 140,
                "pid_params": {"Kp": -1, "Ti": -1, "Td": -1},
                "aggressiveness": 1.0
            }
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(config_path, "w") as f:
                json.dump(config, f, indent=4)

        
        
        self.ftp = config.get("ftp", 200)
        self.target_hr = config.get("target_hr", 140)
        self.pid_params_import = config.get("pid_params", {"Kp": -1, "Ti": -1, "Td": -1})
        self.mult.set(config.get("aggressiveness", 1.0))

        self.ftp_label.config(text=f"{self.ftp} W")
        self.hr_label.config(text=f"{self.target_hr} bpm")
        self.connected_power_trainer_address=config.get("power_trainer_address","")
        self.connected_hr_monitor_address=config.get("hr_monitor_address","")
        
        self.pid_available = not any(
            self.pid_params_import[k] < 0
            for k in ("Kp", "Ti", "Td")
        )

        # 2) Update button colors accordingly
        if self.pid_available:
            # We have PID → test sequence disabled, training enabled
            self.start_sequence_button.config(bg=self.COLOR_DISABLED)
            self.start_training_button.config(bg=self.COLOR_START)
        else:
            # No PID → test sequence enabled, training disabled
            self.start_sequence_button.config(bg=self.COLOR_START)
            self.start_training_button.config(bg=self.COLOR_DISABLED)
        
        
        self.update_aggressiveness(self.mult.get())
        
        self.update_pid_label()

        if self.connected_power_trainer_address and not self.power_client:
            self.log_message(f"Auto-connecting power trainer @ {self.connected_power_trainer_address}…")
            self.power_button.config(bg=self.COLOR_IN_PROCESS)
            self._auto_connect_power(self.connected_power_trainer_address)

        if self.connected_hr_monitor_address and not self.hr_client:
            self.log_message(f"Auto-connecting HR monitor @ {self.connected_hr_monitor_address}…")
            self.hr_button.config(bg=self.COLOR_IN_PROCESS)
            self._auto_connect_hr(self.connected_hr_monitor_address)
        
        # Save last user
        with open(LAST_USER_FILE, "w") as f:
            json.dump({"last_user": username}, f)

    def _auto_connect_power(self, address):
        """Try to connect to a power trainer at `address`."""
        async def cb():
            client = await self.btle.connect(address)
            if client is None:
                self.log_message("Failed to connect to power trainer.")
                self.power_button.config(bg=self.COLOR_ACTION)
            else:
                await self.on_power_trainer_connected(client)
                self.power_connected=True
                if self.pid_available and self.hr_connected and self.power_connected:
                    self.start_training_button.config(bg=self.COLOR_START)
                    self.log_message("You can start the training")
                elif self.hr_connected and self.power_connected and not self.pid_available:
                    self.start_sequence_button(bg=self.COLOR_START)
                    self.log_message("Please run the test sequence first!")

        run_async_task(cb())

    def _auto_connect_hr(self, address):
        """Try to connect to an HR monitor at `address`."""
        async def cb():
            client = await self.btle.connect(address)
            if client is None:
                self.log_message("Failed to connect to HR monitor.")
                self.hr_button.config(bg=self.COLOR_ACTION)
            else:
                await self.on_hr_monitor_connected(client)
                self.hr_connected=True
                if self.pid_available and self.hr_connected and self.power_connected:
                    self.start_training_button.config(bg=self.COLOR_START)
                    self.log_message("You can start the training")
                elif self.hr_connected and self.power_connected and not self.pid_available:
                    self.start_sequence_button(bg=self.COLOR_START)
                    self.log_message("Please run the test sequence first!")

        run_async_task(cb())


            
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
        self.log_message("Searching for Power Trainers")
        self.power_button.config(bg=self.COLOR_IN_PROCESS)
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
        self.log_message("Searching for HR Monitors")
        self.hr_button.config(bg=self.COLOR_IN_PROCESS)
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
        self.connected_power_trainer_address = self.power_client.address
        # ensure you have a StringVar for cadence
        #self.current_cadence = tk.StringVar(value="0 RPM")
        # subscribe
        name = await client.read_gatt_char("00002a00-0000-1000-8000-00805f9b34fb")
        decoded = name.decode(errors="ignore")
        self.root.after(0, lambda: self.connected_power_trainer_name.set(decoded))
        await client.start_notify(
            self.btle.CYCLING_POWER_MEASUREMENT_UUID,
            self.power_handler
        )
        self.root.after(0, lambda: self.power_button.config(bg=self.COLOR_OK))
        self.power_connected=True
        if self.pid_available and self.hr_connected and self.power_connected:
            self.start_training_button.config(bg=self.COLOR_START)
            self.log_message("You can start the training")
        elif self.hr_connected and self.power_connected and not self.pid_available:
            self.start_sequence_button(bg=self.COLOR_START)
            self.log_message("Please run the test sequence first!")

    
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
            self._last_crank_revs = revs
            self._last_crank_event_time = evt

        # update GUI
        self.root.after(0, lambda: self.current_power.set(f"{self.power} W"))
        self.root.after(0, lambda: self.current_cadence.set(f"{self.cadence:.0f} RPM"))
        if cadence is not None:
            self.cadence = cadence
            
    async def set_erg_power(self, watts: int):
        """
        Send the FTMS ‘Set Target Power’ (op‑code 0x05) to the trainer.
        """
        FTMS_CTRL = self.btle.FTMS_CTRL  # Correct UUID for the control point
        # pack: <B = op‑code, H = uint16 watts
        payload = struct.pack("<BH", 0x05, watts)
        print(payload)
        await self.power_client.write_gatt_char(FTMS_CTRL, payload, response=True)
        print(f"Asked trainer to hold {watts} W")



    async def on_hr_monitor_connected(self, client):
        print("HR monitor connected.")
        self.connected_hr_monitor_address = client.address
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
        self.hr_client = client
        self.root.after(0, lambda: self.hr_button.config(bg=self.COLOR_OK))
        self.hr_connected=True
        if self.pid_available and self.hr_connected and self.power_connected:
            self.start_training_button.config(bg=self.COLOR_START)
            self.log_message("You can start the training")
        elif self.hr_connected and self.power_connected and not self.pid_available:
            self.start_sequence_button.config(bg=self.COLOR_START)
            self.log_message("Please run the test sequence first!")




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
