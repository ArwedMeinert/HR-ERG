# Heart Rate ERG Mode
This project implements a heart rate–based control mode for smart cycling trainers—similar in concept to the traditional ERG mode, but targeting a steady heart rate (HR) instead of fixed power.
___
Video:

[![Watch the video](https://img.youtube.com/vi/ws2G1LzrzRw/hqdefault.jpg)](https://youtu.be/ws2G1LzrzRw)

___
## Problem
During long endurance rides at low or steady power, the heart rate often drifts due to fatigue, hydration, or minor disturbances such as talking, adjusting position, or eating. Traditional ERG mode, which fixes the target power, does not account for these effects. The goal of this project is to create a heart rate–controlled feedback loop that adjusts power in real time to maintain a consistent cardiovascular load.
## Solution
Instead of setting a fixed power, this system dynamically adjusts the trainer’s resistance to maintain a user-defined heart rate using a PID (Proportional-Integral-Derivative) controller. The system continuously:

- Measures the current heart rate
- Compares it to the desired target
- Adjusts the power output accordingly to bring the heart rate back on track

This mimics ERG mode behavior but for cardiovascular training.
## System Overview
The Python-based GUI connects to two Bluetooth Low Energy (BLE) devices:

- A heart rate monitor (HRM)
- A smart trainer (supporting BLE ERG mode)

Once connected, the system can either:
- Run a calibration test to automatically tune the PID parameters
- Start a heart-rate–controlled workout
# Setup & Usage
## Pairing 
After launching the GUI, connect both the HR monitor and smart trainer by pressing the "Go" buttons next to each sensor. A list of available BLE devices will be shown for selection.

<img src="https://github.com/user-attachments/assets/3d5c2a35-2c34-446b-9f46-ab437b7dfb08" alt="GUI" width="30%">

## PID Parameters

Before using the control mode, PID parameters must be calibrated:
- Enter your Functional Threshold Power (FTP) in the GUI.
- Click Start Sequence to begin the test protocol.
- Pedal at a cadence above 60 RPM to activate ERG mode.

Test Protocol:
- Trainer sets power to 60% of FTP.
- Once HR stabilizes (no significant change for ~30s), power increases to 90%.
- After HR stabilizes again, power drops and the test ends.

Keep cadence consistent and avoid external influences (e.g. no talking, moving, or adjusting position). The result should resemble the curve below:

<img src="https://github.com/user-attachments/assets/e8346ef8-6471-47ab-931a-9edfaa0c9794" alt="Response" width="60%">


From the response curve, optimal PID parameters are calculated and saved for future use.

## Workout

Once calibrated:
- Set a target heart rate.
- Press Start Training to begin.
- When cadence exceeds 60 RPM, the PID controller activates ERG mode and dynamically adjusts power to match your heart rate to the target.

During the workout, you can change the target heart rate, and the controller will adapt the power accordingly.

At the end of the workout, a plot displays your power, HR, and target HR:

<img src="https://github.com/user-attachments/assets/e78e3e6d-cb2a-4876-abb2-aa833bd182cd" alt="Result" width="60%">

# Result
he system performs well in keeping the heart rate near the target with a delay of ~60 seconds, which is reasonable given:
- Heart rate sensors have a natural delay.
- The human heart rate response is not instantaneous.
- External factors (e.g., drinking water can raise HR by 5 BPM) cause rapid disturbances.

Despite these challenges:
- The system adapts smoothly.
- Power adjustments are gradual and remain within a manageable range.
- Control remains stable even under disturbances.

# Technical Highlights
- Bluetooth LE (BLE) integration for real-time HR and power data.
- PID controller implementation using user-calibrated parameters.
- Asynchronous training loop using asyncio for responsive BLE communication.
- Automatic logging and plotting of workout data for review.

Example data log format:
``` json
{
"timestamp": 102.2,
  "hr": 154,
  "target_hr": 150,
  "power": 284,
  "cadence": 93
}
```

# Future Improvements
- [ ] HR Filter
- [ ] Microcontroller Implementation
- [ ] Online PID Tuning

